#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
Copyright 2012-2015 OpenBroadcaster, Inc.

This file is part of OpenBroadcaster Player.

OpenBroadcaster Player is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

OpenBroadcaster Player is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with OpenBroadcaster Player.  If not, see <http://www.gnu.org/licenses/>.
"""

import obplayer
import obplayer.alerts

import traceback
import time
import datetime

import socket
import sys
import os
import os.path

import requests
import threading


if sys.version.startswith('3'):
    import urllib.parse as urlparse
else:
    import urlparse


class ObAlertFetcher (obplayer.ObThread):
    def __init__(self, processor):
        obplayer.ObThread.__init__(self, 'ObAlertFetcher')
        self.daemon = True

        self.processor = processor
        self.socket = None
        self.buffer = b""
        self.receiving_data = False
        self.last_received = 0
        self.close_lock = threading.Lock()

    def close(self):
        with self.close_lock:
            if self.socket:
                addr, port = self.socket.getsockname()
                obplayer.Log.log("closing socket %s:%s" % (addr, port), 'alerts')
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                    self.socket.close()
                except:
                    #obplayer.Log.log("exception in " + self.name + " thread", 'error')
                    #obplayer.Log.log(traceback.format_exc(), 'error')
                    obplayer.Log.log('error while closing socket', 'error')
                self.socket = None
                self.last_received = 0

    def read_alert_data(self):
        while True:
            if self.buffer:
                if self.receiving_data is False:
                    i = self.buffer.find(b'<?xml')
                    if i >= 0:
                        self.buffer = self.buffer[i:]
                        self.receiving_data = True

                if self.receiving_data is True:
                    data, endtag, remain = self.buffer.partition(b'</alert>')
                    if endtag:
                        self.buffer = remain
                        self.receiving_data = False
                        self.last_received = time.time()
                        return data + endtag

            data = self.receive()
            if not data:
                with self.close_lock:
                    self.socket = None
                raise socket.error("TCP socket closed by remote end. (" + str(self.host) + ":" + str(self.port) + ")")
            self.buffer = self.buffer + data

    def try_run(self):
        while True:
            success = self.connect()
            if not success:
                time.sleep(20)
                continue

            while True:
                try:
                    data = self.read_alert_data()
                    if (data):
                        alert = obplayer.alerts.ObAlert(data)
                        obplayer.Log.log("received alert " + str(alert.identifier) + " (" + str(alert.sent) + ")", 'debug')
                        #alert.print_data()
                        self.processor.dispatch(alert)

                        # TODO for testing only
                        with open(obplayer.ObData.get_datadir() + "/alerts/" + obplayer.alerts.ObAlert.reference(alert.sent, alert.identifier) + '.xml', 'wb') as f:
                            f.write(data)

                except socket.error as e:
                    obplayer.Log.log("Socket Error: " + str(e), 'error')
                    break

                except:
                    obplayer.Log.log("exception in " + self.name + " thread", 'error')
                    obplayer.Log.log(traceback.format_exc(), 'error')
            self.close()
            time.sleep(5)

    def stop(self):
        self.close()


class ObAlertTCPFetcher (ObAlertFetcher):
    def __init__(self, processor, hosts=None):
        ObAlertFetcher.__init__(self, processor)
        self.hosts = hosts

    def connect(self):
        if self.socket is not None:
            self.close()

        for urlstring in self.hosts:
            url = urlparse.urlparse(urlstring, 'http')
            urlparts = url.netloc.split(':')
            (self.host, self.port) = (urlparts[0], urlparts[1] if len(urlparts) > 1 else 80)
            self.socket = None
            try:
                for res in socket.getaddrinfo(self.host, self.port, socket.AF_UNSPEC, socket.SOCK_STREAM):
                    af, socktype, proto, canonname, sa = res

                    try:
                        self.socket = socket.socket(af, socktype, proto)
                        #self.socket.settimeout(360.0)
                    except socket.error as e:
                        self.socket = None
                        continue

                    try:
                        self.socket.connect(sa)
                    except socket.error as e:
                        self.socket.close()
                        self.socket = None
                        continue
                    break
            except socket.gaierror:
                pass

            if self.socket is not None:
                obplayer.Log.log("connected to alert broadcaster at " + str(self.host) + ":" + str(self.port), 'alerts')
                return True

            obplayer.Log.log("error connecting to alert broadcaster at " + str(self.host) + ":" + str(self.port), 'error')
            time.sleep(1)
        return False

    def receive(self):
        return self.socket.recv(4096)

    def send(self, data):
        self.socket.send(data)


class ObAlertUDPFetcher (ObAlertFetcher):
    def __init__(self, processor, hosts=None):
        ObAlertFetcher.__init__(self, processor)
        self.hosts = hosts

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #self.socket.bind(('', self.port))

    def receive(self):
        return self.socket.recv(4096)

    def send(self, data):
        self.socket.sendto(data, (self.host, self.port))


class ObAlertProcessor (object):
    def __init__(self):
        self.lock = threading.Lock()
        self.next_alert_check = 0
        self.last_heartbeat = 0
        self.alerts_seen = { }
        self.alerts_active = { }
        self.alerts_expired = { }

        self.alert_queue = [ ]
        self.dispatch_lock = threading.Lock()

        #self.streaming_hosts = [ "streaming1.naad-adna.pelmorex.com:8080", "streaming2.naad-adna.pelmorex.com:8080" ]
        #self.archive_hosts = [ "capcp1.naad-adna.pelmorex.com", "capcp2.naad-adna.pelmorex.com" ]
        self.streaming_hosts = [ obplayer.Config.setting('alerts_naad_stream1'), obplayer.Config.setting('alerts_naad_stream2') ]
        self.archive_hosts = [ obplayer.Config.setting('alerts_naad_archive1'), obplayer.Config.setting('alerts_naad_archive2') ]
        self.target_geocodes = [ geocode.strip() for geocode in obplayer.Config.setting('alerts_geocode').split(',') ]
        self.repeat_interval = obplayer.Config.setting('alerts_repeat_interval')
        self.repeat_times = obplayer.Config.setting('alerts_repeat_times')
        self.leadin_delay = obplayer.Config.setting('alerts_leadin_delay')
        self.leadout_delay = obplayer.Config.setting('alerts_leadout_delay')
        self.language_primary = obplayer.Config.setting('alerts_language_primary')
        self.language_secondary = obplayer.Config.setting('alerts_language_secondary')
        self.voice_primary = obplayer.Config.setting('alerts_voice_primary')
        self.voice_secondary = obplayer.Config.setting('alerts_voice_secondary')

        self.play_moderates = obplayer.Config.setting('alerts_play_moderates')
        self.play_tests = obplayer.Config.setting('alerts_play_tests')

        self.triggers = [ ]

        if obplayer.Config.setting('alerts_trigger_serial'):
            from obplayer.alerts.triggers.rs232 import SerialTrigger
            self.triggers.append(SerialTrigger())

        if obplayer.Config.setting('alerts_trigger_streamer'):
            from obplayer.alerts.triggers.streamer import StreamerTrigger
            self.triggers.append(StreamerTrigger())

        if obplayer.Config.setting('led_sign_enable'):
            from obplayer.alerts.triggers.ledsign import LEDSignTrigger
            self.triggers.append(LEDSignTrigger())


        self.ctrl = obplayer.Player.create_controller('alerts', priority=100, default_play_mode='overlap', allow_overlay=True)
        #self.ctrl.do_player_request = self.do_player_request

        self.thread = obplayer.ObThread('ObAlertProcessor', target=self.run)
        self.thread.daemon = True
        self.thread.start()

        self.fetcher = ObAlertTCPFetcher(self, self.streaming_hosts)
        self.fetcher.start()

    def dispatch(self, alert):
        with self.lock:
            self.alert_queue.insert(0, alert)

    def cancel_alert(self, identifier):
        if identifier in self.alerts_active:
            self.mark_expired(self.alerts_active[identifier])

    def inject_alert(self, filename):
        obplayer.Log.log("injecting test alert from file " + filename, 'alerts')
        with open(filename, 'rb') as f:
            data = f.read()
        alert = obplayer.alerts.ObAlert(data)
        alert.add_geocode(self.target_geocodes[0])
        alert.max_plays = 1
        #alert.print_data()
        self.dispatch(alert)

    def get_alert(self, identifier):
        with self.lock:
            if identifier in self.alerts_active:
                return self.alerts_active[identifier]
            elif identifier in self.alerts_expired:
                return self.alerts_expired[identifier]
            else:
                return False

    def get_alerts(self):
        alerts = { 'active' : [ ], 'expired' : [ ], 'last_heartbeat' : self.last_heartbeat, 'next_play' : self.next_alert_check }
        with self.lock:
            for (name, alert_list) in [ ('active', self.alerts_active), ('expired', self.alerts_expired) ]:
                for alert in self.sort_by_importance(alert_list.values()):
                    info = alert.get_first_info(self.language_primary)
                    alerts[name].append({
                        'identifier' : alert.identifier,
                        'sender' : alert.sender,
                        'sent' : alert.sent,
                        'headline' : info.headline.capitalize(),
                        'description' : info.description,
                        'played' : alert.times_played
                    })
        return alerts

    def mark_seen(self, alert):
        with self.lock:
            self.alerts_seen[alert.identifier] = True

    def mark_active(self, alert):
        if alert.active is not True:
            with self.lock:
                self.alerts_active[alert.identifier] = alert
                alert.active = True

    def mark_expired(self, alert):
        if alert.active is not False:
            with self.lock:
                alert.active = False
                del self.alerts_active[alert.identifier]
                self.alerts_expired[alert.identifier] = alert

    def handle_dispatch(self, alert):
        # mark the alert as seen
        seen = True if alert.identifier in self.alerts_seen else False
        self.mark_seen(alert)

        # if first time seen, then fetch alerts
        if not seen and alert.status == 'system':# or alert.msgtype == 'update':
            self.fetch_references(alert.references, required=True if alert.status == 'system' else False)

        # deactivate any previous alerts that are cancelled or superceeded by this alert
        if alert.msgtype in ('update', 'cancel'):
            for (_, identifier, _) in alert.references:
                if identifier in self.alerts_active:
                    alert.previously_important = self.alerts_active[identifier].broadcast_immediately()     # message updates might not have the BI flag set
                    self.mark_expired(self.alerts_active[identifier])

        if alert.status == 'system':
            self.last_heartbeat = time.time()

        elif alert.msgtype in ('alert', 'update'):
            if self.match_alert_conditions(alert):
                self.mark_active(alert)
                if not alert.minor_change():
                    self.next_alert_check = time.time() + 20

    def match_alert_conditions(self, alert):
        if not alert.has_geocode(self.target_geocodes):
            return False

        if self.play_tests is True and alert.status == 'test':
            return True

        if alert.status != 'actual' or alert.scope != 'public':
            return False

        if alert.broadcast_immediately():
            # TODO this now happens elsewhere
            #self.next_alert_check = time.time()
            return True

        # if the broadcast immediately flag is not set and we aren't playing moderate severity alerts, then return false
        if self.play_moderates is True:
            return True

        return False

    def fetch_references(self, references, required=False):
        for (sender, identifier, timestamp) in references:
            if not identifier in self.alerts_seen:
                self.fetch_reference(sender, identifier, timestamp, required)

    def fetch_reference(self, sender, identifier, timestamp, required=False):
        (urldate, _, _) = timestamp.partition('T')
        filename = obplayer.alerts.ObAlert.reference(timestamp, identifier)

        for host in self.archive_hosts:
            url = "%s/%s/%s.xml" % (host, urldate, filename)
            try:
                obplayer.Log.log("fetching alert %s using url %s" % (identifier, url), 'debug')
                r = requests.get(url)

                if r.status_code == 200:
                    #r.encoding = 'utf-8'
                    with open(obplayer.ObData.get_datadir() + "/alerts/" + filename + '.xml', 'wb') as f:
                        f.write(r.content)

                    alert = obplayer.alerts.ObAlert(r.content)
                    self.handle_dispatch(alert)
                    return
            except requests.ConnectionError:
                pass
        obplayer.Log.log("error fetching alert %s" % (identifier,), 'error' if required else 'debug')

    def trigger_alert_cycle_start(self):
        for trigger in self.triggers:
            try:
                trigger.alert_cycle_start()
            except:
                obplayer.Log.log("error during alert cycle start trigger", 'error')
                obplayer.Log.log(traceback.format_exc(), 'error')

    def trigger_alert_cycle_stop(self):
        for trigger in self.triggers:
            try:
                trigger.alert_cycle_stop()
            except:
                obplayer.Log.log("error during alert cycle stop trigger", 'error')
                obplayer.Log.log(traceback.format_exc(), 'error')

    def trigger_alert_cycle_init(self):
        for trigger in self.triggers:
            try:
                trigger.alert_cycle_init()
            except:
                obplayer.Log.log("error during alert cycle init trigger", 'error')
                obplayer.Log.log(traceback.format_exc(), 'error')

    def trigger_alert_cycle_each(self, alert, alert_media, processor):
        for trigger in self.triggers:
            try:
                trigger.alert_cycle_each(alert, alert_media, processor)
            except:
                obplayer.Log.log("error during alert cycle each trigger", 'error')
                obplayer.Log.log(traceback.format_exc(), 'error')

    def sort_by_importance(self, alerts):
        return sorted(alerts, key=lambda alert: alert.received_at * (10000 if alert.broadcast_immediately() else 1), reverse=True)

    def run(self):
        self.next_purge_check = time.time() if obplayer.Config.setting('alerts_purge_files') else None
        self.next_expired_check = time.time() + 30
        self.next_alert_check = time.time()

        while not self.thread.stopflag.wait(1):
            try:
                present_time = time.time()

                # process alerts waiting in the dispatch queue
                if len(self.alert_queue) > 0:
                    alert = None
                    with self.lock:
                        alert = self.alert_queue.pop()

                    with self.dispatch_lock:
                        self.handle_dispatch(alert)

                # deactivate alerts that have expired
                if present_time > self.next_expired_check:
                    self.next_expired_check = present_time + 30
                    expired_list = [ ]
                    with self.lock:

                        for alert in self.alerts_active.values():
                            if alert.is_expired():
                                obplayer.Log.log("alert %s has expired" % (obplayer.alerts.ObAlert.reference(alert.sent, alert.identifier),), 'alerts')
                                expired_list.append(alert)
                    for alert in expired_list:
                        self.mark_expired(alert)

                # delete old alert data
                if self.next_purge_check is not None and present_time > self.next_purge_check:
                    self.next_purge_check = present_time + 86400

                    basedir = obplayer.ObData.get_datadir() + "/alerts"
                    then = datetime.datetime.now() - datetime.timedelta(days=90)

                    for filename in os.listdir(basedir):
                        try:
                            (year, month, day) = filename[:10].split('_')
                            filedate = datetime.datetime(int(year), int(month), int(day))
                            if filedate < then:
                                obplayer.Log.log("deleting alert file " + filename, 'debug')
                                os.remove(os.path.join(basedir, filename))
                        except:
                            pass

                # play active alerts
                if present_time > self.next_alert_check:
                    if len(self.alerts_active) > 0:
                        obplayer.Log.log("playing active alerts (%d alert(s) to play)" % (len(self.alerts_active),), 'alerts')

                        self.ctrl.hold_requests(True)
                        self.ctrl.add_request(media_type='break', title="alert lead in delay", duration=self.leadin_delay, onstart=self.trigger_alert_cycle_start)

                        expired_list = [ ]
                        with self.lock:
                            self.trigger_alert_cycle_init()

                            for alert in self.sort_by_importance(self.alerts_active.values()):
                                alert_media = alert.get_media_info(self.language_primary, self.voice_primary, self.language_secondary, self.voice_secondary)
                                if alert_media['primary']:
                                    alert.times_played += 1

                                    start_time = self.ctrl.get_requests_endtime()
                                    if alert.times_played <= 1:
                                        #TODO Remove this and add it's settings to the config system.
                                        if os.path.isfile("obplayer/alerts/data/ledin_message.ogg"):
                                            self.ctrl.add_request(media_type='audio', uri=obplayer.Player.file_uri("obplayer/alerts/data", "ledin_message.ogg"), duration=8, artist=alert_media['primary']['audio']['artist'], title=alert_media['primary']['audio']['title'], overlay_text=alert_media['primary']['audio']['overlay_text'])
                                        self.ctrl.add_request(media_type='break', title="alert tone delay", duration=1.0)
                                        self.ctrl.add_request(media_type='audio', uri=obplayer.Player.file_uri("obplayer/alerts/data", "canadian-attention-signal.mp3"), duration=8, artist=alert_media['primary']['audio']['artist'], title=alert_media['primary']['audio']['title'], overlay_text=alert_media['primary']['audio']['overlay_text'])
                                    self.ctrl.add_request(**alert_media['primary']['audio'])
                                    if 'visual' in alert_media['primary']:
                                        self.ctrl.add_request(start_time=start_time, **alert_media['primary']['visual'])

                                    if alert_media['secondary']:
                                        start_time = self.ctrl.get_requests_endtime()
                                        self.ctrl.add_request(**alert_media['secondary']['audio'])
                                        if 'visual' in alert_media['secondary']:
                                            self.ctrl.add_request(start_time=start_time, **alert_media['secondary']['visual'])

                                    self.trigger_alert_cycle_each(alert, alert_media, self)

                                    if (self.repeat_times > 0 and alert.times_played >= self.repeat_times) or (alert.max_plays > 0 and alert.times_played >= alert.max_plays):
                                        expired_list.append(alert)

                        self.ctrl.add_request(media_type='break', title="alert lead out delay", duration=self.leadout_delay, onend=self.trigger_alert_cycle_stop)
                        self.ctrl.adjust_request_times(time.time())
                        self.ctrl.hold_requests(False)

                        for alert in expired_list:
                            self.mark_expired(alert)

                    self.next_alert_check = self.ctrl.get_requests_endtime() + (self.repeat_interval * 60)

                    """
                    print("Starting")
                    for req in self.ctrl.queue:
                        print("{start_time} {end_time} {media_type}".format(**req))
                    print("Ending")
                    """

                # reset fetcher if we stop receiving heartbeats
                if self.fetcher.last_received and time.time() - self.fetcher.last_received > 360:
                    obplayer.Log.log("no heartbeat received for 6 min. resetting alert fetcher.", 'error')
                    # Play beep after no heartbeats for 6 minutes.
                    os.system("play -q -n synth 0.8 sin 880; sleep 1; play -q -n synth 0.8 sin 880; sleep 1; play -q -n synth 0.8 sin 880; sleep 1; play -q -n synth 0.8 sin 880")
                    self.fetcher.close()

            except:
                obplayer.Log.log("exception in " + self.thread.name + " thread", 'error')
                obplayer.Log.log(traceback.format_exc(), 'error')


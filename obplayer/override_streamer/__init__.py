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

from __future__ import absolute_import

import obplayer
import requests
import time
import subprocess
import json

class Streamer(obplayer.ObThread):
    def __init__(self):
        obplayer.ObThread.__init__(self, 'Obremote_station_override')
        #self.ctrl = obplayer.Player.create_controller('remote station override', priority=99, allow_requeue=False, default_play_mode='overlap')
        self.ctrl = obplayer.Player.create_controller('remote station override', priority=99, allow_requeue=False)
        self.ffmpeg = None
        self.stream_active = False
        self.running = True
        self.daemon = True


    def start_override(self, url):
        print('Starting Override...')
        self.ffmpeg = subprocess.Popen(['ffmpeg', '-loglevel', 'quiet', '-re', '-i', url, '-c:a', 'pcm_s16le', '-f', 'rtp', 'rtp://localhost:5000'], stdout=subprocess.PIPE)
        #print(self.ffmpeg.poll())
        #self.ctrl.add_request(media_type='rtp_2', start_time=time.time() + 4, duration=153)
        self.ctrl.add_request(media_type='rtp', start_time=time.time() + 4, duration=153, uri="rtp://localhost:5000")

    def stop_override(self):
        if self.ffmpeg != None:
            self.ffmpeg.kill()

    def check_stream_status(self, stats_url, stream_url):
        req = requests.get(stats_url)
        #print(req.content.decode())
        if req.status_code == 200:
            try:
                data = json.loads(req.content.decode())
                try:
                    if data['icestats'].get('source') != None:
                        if data['icestats']['source']['listenurl'] == stream_url.replace('127.0.0.1', 'localhost'):
                            print('True')
                            return True
                    print('False')
                    return False
                except Exception as e:
                    for stream in data['icestats']['source']:
                        if stream_url == stream['listenurl'].replace('127.0.0.1', 'localhost'):
                            print('TEST:' + stream['listenurl'])
                            return True
            except Exception as e:
                #print(e)
                #print('TEST')
                #print(req.content)
                return False
        else:
            return False

    def background(self):
        ip = obplayer.Config.setting('station_override_server_ip')
        port = obplayer.Config.setting('station_override_server_port')
        mountpoint = obplayer.Config.setting('station_override_server_mountpoint')
        stream_url = 'http://{0}:{1}/{2}'.format(ip, port, mountpoint)
        while self.running:
            if self.check_stream_status('http://{0}:{1}/status-json.xsl'.format(ip, port), stream_url) and self.stream_active == False:
                print('Override stream Found...')
                self.stream_active = True
                self.start_override(stream_url)
            time.sleep(6)
        if self.stream_active:
            self.stop_override()


    def try_run(self):
        try:
            self.background()
            #print('Testing override...')
            #self.ctrl.add_request(media_type='rtp_2', start_time=time.time(), duration=153)
        except Exception as e:
            print(e)
            raise

    def stop(self):
        self.running = False

# def linein_request(self, present_time, media_class):
#     self.add_request(media_type='linein', duration=31536000)        # duration = 1 year (ie. indefinitely)
#
# def background(self):
#     stream_active = False
#     ip = obplayer.Config.setting('station_override_server_ip')
#     port = obplayer.Config.setting('station_override_server_port')
#     mountpoint = obplayer.Config.setting('station_override_server_mountpoint')
#     stream_url = 'http://{0}:{1}/{2}'.format(ip, port, mountpoint)
#     while self.running:
#         req = requests.get(stream_url)
#         if req.status_code == 200:
#             stream_active = True




def init():
    streamer = Streamer()
    streamer.start()
    #print('TEST 4')
    #ctrl = obplayer.Player.create_controller('linein', priority=10, allow_requeue=False)
    #def linein_request(self, present_time, media_class):
    #     self.add_request(media_type='linein', duration=31536000)        # duration = 1 year (ie. indefinitely)
    #ctrl = obplayer.Player.create_controller('linein', priority=99, allow_requeue=False)
    #ctrl.set_request_callback(linein_request)

def quit():
    pass

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
        self.ctrl = obplayer.Player.create_controller('remote station override', priority=99)
        self.ffmpeg = None
        self.stream_active = False
        self.running = True
        self.daemon = True
        self.self_sending_override = False

    def start_override(self, url):
        #print('Starting Override...')
        self.ffmpeg = subprocess.Popen(['ffmpeg', '-loglevel', 'quiet', '-re', '-i', url, '-c:a', 'libopus', '-f', 'rtp', 'rtp://127.0.0.1:5000'], stdout=subprocess.PIPE)
        self.ctrl.add_request(media_type='remote_audio', start_time=time.time() + 4, duration=31536000, uri="rtp://127.0.0.1:5000")

    def stop_override(self):
        if self.ffmpeg != None:
            #print('Ending Override...')
            self.ffmpeg.kill()
            self.ffmpeg = None
        self.ctrl.stop_requests()
        self.ctrl.add_request(media_type='break', duration=1)

    def check_stream_status(self, stats_url, stream_url):
        req = requests.get(stats_url)
        if req.status_code == 200:
            try:
                data = json.loads(req.content.decode())
                try:
                    if data['icestats'].get('source') != None:
                        if data['icestats']['source']['listenurl'] == stream_url.replace('127.0.0.1', 'localhost'):
                            return True
                    return False
                except Exception as e:
                    for stream in data['icestats']['source']:
                        if stream_url == stream['listenurl'].replace('127.0.0.1', 'localhost'):
                            return True
            except Exception as e:
                #print(e)
                return False
        else:
            return False

    def background(self):
        mountpoints = obplayer.Config.setting('station_override_monitored_streams').split(',')
        while self.running:
            for mountpoint in mountpoints:
                data = mountpoint.split(':')
                ip = data[1].replace('//', '')
                port = data[2].replace('//', '').split('/')[0]
                mountpoint = data[2].replace('//', '').split('/')[1]
                stream_url = 'http://{0}:{1}/{2}'.format(ip, port, mountpoint)
                if self.check_stream_status('http://{0}:{1}/status-json.xsl'.format(ip, port), stream_url):
                    #print('Override stream Found...')
                    if self.stream_active == False:
                        self.stream_active = True
                        self.start_override(stream_url)
                else:
                    if self.stream_active:
                        self.stop_override()
                    self.stream_active = False
            time.sleep(6)


    def try_run(self):
        try:
            self.background()
        except Exception as e:
            print(e)
            raise

    def stop(self):
        self.running = False

def init():
    streamer = Streamer()
    streamer.start()

def quit():
    pass

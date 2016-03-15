#!/usr/bin/python
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

import os
import sys
import time
import traceback

import subprocess


output = None
modes = [ ]

def init():
    load_modes()
    mode = obplayer.Config.setting('video_out_resolution')
    if not obplayer.Config.headless:
        set_mode(mode)

def load_modes():
    global modes, output
    modes = [ ]

    proc = subprocess.Popen([ 'xrandr' ], stdout=subprocess.PIPE)
    (output, _) = proc.communicate()

    displays = [ ]
    for line in output.split(b'\n'):
        if line.startswith(b' '):
            if len(displays) < 0:
                obplayer.Log.log("error reading output of xrandr", 'error')
                break
            displays[-1].append(line.strip().split()[0])
        elif b' connected' in line:
            displays.append([ line ])

    #print(displays)

    use = None
    for display in displays:
        if b'connected primary' in display[0]:
            use = display
            break
    if not use:
        use = displays[0]

    output = use[0].decode('utf-8').split(' ')[0]
    for mode in use[1:]:
        modes.append(mode.decode('utf-8'))

    #print(output)
    #print(modes)

def get_modes():
    return modes.copy()

def set_mode(mode):
    if mode == 'default':
        return

    if mode not in modes:
        obplayer.Log.log("invalid xrandr video mode " + mode, 'error')
        return

    obplayer.Log.log("changing xrandr video mode to " + mode, 'player')
    os.system('xrandr --output {0} --mode {1}'.format(output, mode))


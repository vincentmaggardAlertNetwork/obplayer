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

import xml.dom.minidom
import base64
import hashlib
import datetime
import dateutil.tz
import dateutil.parser

import os
import os.path
import sys
import time
import socket

import traceback

import cgi
import requests
import subprocess

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstPbutils', '1.0')
from gi.repository import GObject, Gst, GstPbutils

def xml_get_text(element):
    text = ''
    for node in element.childNodes:
        if node.nodeType == node.TEXT_NODE:
            text = text + node.data
    return text

def xml_has_tag(element, tag):
    for node in element.childNodes:
        if node.nodeType == node.ELEMENT_NODE and node.nodeName == tag:
            return True
    return False

def xml_get_tags(element, tag):
    children = [ ]
    for node in element.childNodes:
        if node.nodeType == node.ELEMENT_NODE and node.nodeName == tag:
            children.append(node)
    return children

def xml_get_tag_values(element, tag):
    values = [ ]
    for child in xml_get_tags(element, tag):
        values.append(xml_get_text(child))
    return values

def xml_get_first_tag_value(element, tag, default=None):
    children = xml_get_tags(element, tag)
    if len(children) <= 0:
        return default
    return xml_get_text(children[0])



class ObAlert (object):
    def __init__(self, xmlcode=None):
        self.active = False
        self.max_plays = 0
        self.times_played = 0
        self.previously_important = False
        self.media_info = { }
        self.received_at = time.time()

        if xmlcode is not None:
            self.parse_cap_xml(xmlcode)

    def parse_cap_xml(self, xmlcode):
        try:
            alerts = xml.dom.minidom.parseString(xmlcode)
        except:
            obplayer.Log.log('error parsing emergency alert xml data', 'error')
            obplayer.Log.log(traceback.format_exc(), 'error')
            print(xmlcode)
            return

        for alert in alerts.getElementsByTagName('alert'):
            self.identifier = xml_get_first_tag_value(alert, 'identifier')
            self.sender = xml_get_first_tag_value(alert, 'sender')
            self.sent = xml_get_first_tag_value(alert, 'sent')
            self.codes = xml_get_tag_values(alert, 'code')
            self.status = xml_get_first_tag_value(alert, 'status', default="").lower()
            self.msgtype = xml_get_first_tag_value(alert, 'msgType', default="").lower()
            self.scope = xml_get_first_tag_value(alert, 'scope', default="").lower()
            self.references = [ ref.split(',') for ref in xml_get_first_tag_value(alert, 'references', default="").split() ]

            self.info = [ ]
            for node in xml_get_tags(alert, 'info'):
                self.info.append(ObAlertInfo(node))

            self.signatures = [ ]
            for signature in xml_get_tags(alert, 'Signature'):
                self.signatures.append(ObAlertSignature(signature))


    def print_data(self):
        print(self.identifier)
        print(self.sent + " by " + self.sender)
        print("Status: " + self.status + " Type: " + self.msgtype)

        if len(self.info) > 0:
            print(self.info[0].description)

    def get_all_info(self, language):
        infos = [ ]
        lang = self.lang_ref(language)
        for info in self.info:
            if info.language == lang:
                infos.append(info)
        return infos

    def get_first_info(self, language, bestmatch=True):
        lang = self.lang_ref(language)
        for info in self.info:
            if info.language == lang:
                return info
        if bestmatch and len(self.info) > 0:
            return self.info[0]
        return None

    def has_geocode(self, codes):
        for info in self.info:
            for area in info.areas:
                if area.has_geocode(codes):
                    return True
        return False

    def add_geocode(self, code):
        for info in self.info:
            for area in info.areas:
                area.add_geocode(code)

    def is_expired(self):
        for info in self.info:
            if not info.is_expired():
                return False
        return True

    def broadcast_immediately(self):
        if self.previously_important:
            return True
        for info in self.info:
            val = info.get_parameter("layer:SOREM:1.0:Broadcast_Immediately")
            if val.lower() == "yes":
                return True
        return False

    def minor_change(self):
        for info in self.info:
            val = info.get_parameter("profile:CAP-CP:0.4:MinorChange")
            if val:
                return val
        return None

    def generate_audio(self, language, voice=None):
        info = self.get_first_info(language, bestmatch=False)
        if info is None:
            self.media_info[language] = None
            return False

        truncate = not self.broadcast_immediately() and obplayer.Config.setting('alerts_truncate')
        message_text = info.get_message_text(truncate)

        # TODO there needs to be a better way to get the datadir
        location = obplayer.ObData.get_datadir() + "/alerts"
        if os.access(location, os.F_OK) == False:
            os.mkdir(location)
        filename = self.reference(self.sent, self.identifier) + "-" + language + ".wav"
        uri = obplayer.Player.file_uri(location, filename)

        resources = info.get_resources('audio')
        if resources:
            if resources[0].write_file(os.path.join(location, filename)) is False:
                return False

        elif message_text:
            self.write_tts_file(os.path.join(location, filename), message_text, voice)

        else:
            return False

        d = GstPbutils.Discoverer()
        mediainfo = d.discover_uri(uri)

        self.media_info[language] = { }
        self.media_info[language]['audio'] = {
            'media_type' : 'audio',
            'artist' : 'Emergency Alert',
            'title' : str(self.identifier),
            'overlay_text' : message_text,
            'uri' : uri,
            'duration' : (mediainfo.get_duration() / float(Gst.SECOND))
        }

        # the NPAS Common Look and Feel guide states that audio content should not be more than 120 seconds
        if self.media_info[language]['audio']['duration'] > 120.0:
            self.media_info[language]['audio']['duration'] = 120.0

        resources = info.get_resources('image')
        if resources:
            filename = self.reference(self.sent, self.identifier) + "-" + language + ".jpg"
            if resources[0].write_file(os.path.join(location, filename)) is False:
                return False
            self.media_info[language]['visual'] = {
                'media_type' : 'image',
                'artist' : 'Emergency Alert',
                'title' : str(self.identifier),
                #'overlay_text' : message_text,
                'uri' : obplayer.Player.file_uri(location, filename),
                'duration' : self.media_info[language]['audio']['duration']
            }
            self.media_info[language]['audio']['overlay_text'] = None

        return True

    def get_media_info(self, primary_language, primary_voice, secondary_language, secondary_voice):
        if primary_language not in self.media_info:
            self.generate_audio(primary_language, primary_voice)
        if secondary_language and secondary_language not in self.media_info:
            self.generate_audio(secondary_language, secondary_voice)
        if primary_language not in self.media_info or self.media_info[primary_language] is None:
            return { 'primary' : self.media_info[secondary_language], 'secondary' : None }
        return { 'primary': self.media_info[primary_language], 'secondary' : self.media_info[secondary_language] if secondary_language else None }

    def write_tts_file(self, path, message_text, voice=None):
        if not voice:
            voice = 'en'
        message_text = message_text.rstrip('*')
        #os.system("echo \"%s\" | text2wave > %s/%s" % (message_text[0], location, filename))
        #os.system(u"espeak -v %s -s 130 -w %s/%s \"%s\"" % (voice, location, filename, message_text[0].encode('utf-8')))
        #cmd = u"espeak -v %s -s 130 -w %s/%s " % (voice, location, filename)
        #cmd += u"\"" + message_text[0] + u"\""
        proc = subprocess.Popen([ 'espeak', '-m', '-v', voice, '-s', '130', '--stdout' ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=True)
        message_text = cgi.escape(message_text).encode('utf-8')
        (stdout, stderr) = proc.communicate(message_text + b" <break time=\"2s\" /> " + message_text + b" <break time=\"3s\" /> ")
        proc.wait()

        with open(path, 'wb') as f:
            f.write(stdout)

    @staticmethod
    def reference(timestamp, identifier):
        reference = timestamp + "I" + identifier
        reference = reference.translate({ ord('-') : ord('_'), ord(':') : ord('_'), ord('+') : ord('p') })
        return reference

    @staticmethod
    def lang_ref(language):
        if language == 'english':
            return 'en-CA'
        elif language == 'french':
            return 'fr-CA'
        elif language == 'cree':
            return 'cr-CA'
        elif language == 'inuktitut':
            return 'iu-CA'
        elif language == 'ojibwe':
            return 'oj-CA'
        elif language == 'chipewyan':
            return 'chp-CA'
        elif language == 'mikmaq':
            return 'mic-CA'
        else:
            raise Exception("Unsupported language: " + language)


class ObAlertInfo (object):
    def __init__(self, element):
        self.parse_info(element)

    def parse_info(self, info):
        self.language = xml_get_first_tag_value(info, 'language', 'en-US')
        self.event = xml_get_first_tag_value(info, 'event')
        self.urgency = xml_get_first_tag_value(info, 'urgency')
        self.severity = xml_get_first_tag_value(info, 'severity')
        self.certainty = xml_get_first_tag_value(info, 'certainty')

        self.effective = xml_get_first_tag_value(info, 'effective')
        self.onset = xml_get_first_tag_value(info, 'onset')
        self.expires = xml_get_first_tag_value(info, 'expires')

        self.categories = xml_get_tag_values(info, 'category')
        self.responsetypes = xml_get_tag_values(info, 'responseType')

        self.sender = xml_get_first_tag_value(info, 'senderName')
        self.headline = xml_get_first_tag_value(info, 'headline')
        self.description = xml_get_first_tag_value(info, 'description')
        self.instruction = xml_get_first_tag_value(info, 'instruction')

        self.parameters = [ ]
        for parameter in xml_get_tags(info, 'parameter'):
            name = xml_get_first_tag_value(parameter, 'valueName')
            val = xml_get_first_tag_value(parameter, 'value')
            if val is not None:
                self.parameters.append([ name, val ])

        self.eventcodes = [ ]
        for eventcode in xml_get_tags(info, 'eventCode'):
            name = xml_get_first_tag_value(eventcode, 'valueName')
            code = xml_get_first_tag_value(eventcode, 'value')
            if code is not None:
                self.eventcodes.append([ name, code ])

        self.areas = [ ]
        for node in xml_get_tags(info, 'area'):
            self.areas.append(ObAlertArea(node))

        self.resources = [ ]
        for node in xml_get_tags(info, 'resource'):
            self.resources.append(ObAlertResource(node))

    def is_expired(self):
        if self.expires:
            current = datetime.datetime.now(dateutil.tz.tzlocal())
            expires = dateutil.parser.parse(self.expires)
            if current > expires:
                return True
        return False

    def get_parameter(self, name):
        for param in self.parameters:
            if param[0] == name:
                return param[1]
        return None

    def get_resources(self, typename=None):
        return [ resource for resource in self.resources if not typename or typename in resource.mimetype ]

    def get_message_text(self, truncate=False):
        text = self.get_parameter("layer:SOREM:1.0:Broadcast_Text")
        if not text:
            #text = self.description if self.description else self.headline
            # CLF Guide 1.2: Appendix D, Section 2.2
            sender = ' - ' + self.sender if self.sender else ''
            areadesc = ' - ' + ', '.join([ area.description for area in self.areas ])
            instruction = ' - ' + self.instruction if self.instruction else ''
            if self.language == 'fr-CA':
                text = 'Alerte' + sender + ' - ' + 'Alerte ' + self.event + areadesc + instruction
            else:
                text = 'Alert' + sender + ' - ' + self.event + ' Alert' + areadesc + instruction

        if sys.version.startswith('3'):
            import html
            text = html.unescape(text)
        else:
            text = text.replace('&apos;', "\'").replace('&quot;', '\"').replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<').replace('&#xA;', '\n')

        if truncate:
            parts = text.split('\n\n', 1)
            text = parts[0] + ('***' if len(parts) > 1 else '')

        text = text.replace('\n', ' ').replace('\r', '')
        return text


class ObAlertArea (object):
    def __init__(self, element):
        self.parse_area(element)

    def parse_area(self, area):
        self.description = xml_get_first_tag_value(area, 'areaDesc')
        self.altitude = xml_get_first_tag_value(area, 'altitude')
        self.ceiling = xml_get_first_tag_value(area, 'ceiling')

        self.polygons = xml_get_tag_values(area, 'polygon')
        self.circles = xml_get_tag_values(area, 'circle')

        self.geocodes = [ ]
        for geocode in xml_get_tags(area, 'geocode'):
            name = xml_get_first_tag_value(geocode, 'valueName')
            code = xml_get_first_tag_value(geocode, 'value')
            if code is not None:
                self.geocodes.append([ name, code ])

    def has_geocode(self, codes):
        for geocode in self.geocodes:
            for code in codes:
                # TODO this is a bit of a hack
                if geocode[0] == 'profile:CAP-CP:Location:0.3' and (geocode[1].startswith(code) or code.startswith(geocode[1])):
                    return True
        return False

    def add_geocode(self, code):
        self.geocodes.append([ 'profile:CAP-CP:Location:0.3', code ])


class ObAlertResource (object):
    def __init__(self, element):
        self.parse_resource(element)

    def parse_resource(self, resource):
        self.description = xml_get_first_tag_value(resource, 'resourceDesc')
        self.mimetype = xml_get_first_tag_value(resource, 'mimeType')

        self.size = xml_get_first_tag_value(resource, 'size')
        self.uri = xml_get_first_tag_value(resource, 'uri')

        self.data = None
        derefuri = xml_get_first_tag_value(resource, 'derefUri')
        if derefuri is not None:
            digest = xml_get_first_tag_value(resource, 'digest')
            calculated_digest = hashlib.sha1(derefuri.encode('utf-8')).hexdigest()
            if digest != calculated_digest:
                obplayer.Log.log("emergency alert resource corrupted: " + str(self.uri), 'error')
            else:
                try:
                    self.data = base64.b64decode(derefuri)
                except:
                    obplayer.Log.log("error parsing base64 resource from emergency alert", 'error')

        elif self.uri is not None:
            try:
                obplayer.Log.log("fetching alert resource %s" % (self.uri,), 'alerts')
                r = requests.get(self.uri)

                if r.status_code == requests.codes.ok:
                    self.data = r.content
                else:
                    obplayer.Log.log("error fetching alert resource %s: returned status code %s" % (self.uri, r.status_code), 'alerts')
            #except requests.exceptions.RequestException:
            except:
                obplayer.Log.log("connection error while fetching alert resource %s" % (self.uri,), 'alerts')

    def write_file(self, filename):
        if not self.data:
            return False
        with open(filename, 'wb') as f:
            f.write(self.data)


class ObAlertSignature (object):
    def __init__(self, element):
        self.parse_signature(element)

    def parse_signature(self, signature):
        self.signed_info = xml_get_first_tag_value(signature, 'SignedInfo')
        # TODO finish this, although it's not clear from the cap specs if you're suppose to reject a message that isn't verified or signed



def parse_alert_file(xmlfile):
    with open(xmlfile, 'rb') as f:
        alert = ObAlert(f.read())
    return alert


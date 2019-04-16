import obplayer
import subprocess
import wave

class Recorder(obplayer.ObThread):
    def __init__(self, output_file):
        obplayer.ObThread.__init__(self, 'Oboff_air_AudioLog-Recorder')
        self.daemon = True
        self.output_file = output_file
        self.audio_data = []
        self.recording = False
        fm_feq = str(obplayer.Config.setting('offair_audiolog_feq'))
        sample_rate = '8000'
        icecast_location = obplayer.Config.setting('offair_audiolog_icecast_ip') + ':' + obplayer.Config.setting('offair_audiolog_icecast_port')
        icecast_mountpoint = obplayer.Config.setting('offair_audiolog_icecast_mountpoint')
        icecast_password = obplayer.Config.setting('offair_audiolog_icecast_password')
        icecast_bitrate = obplayer.Config.setting('offair_audiolog_icecast_bitrate')

        self.process = subprocess.Popen(['rtl_fm', '-f', fm_feq + 'M', '-M', 'wbfm', '-r', sample_rate], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if self.process.poll() != None:
            obplayer.Log.log("Could not start off-air audio log.\n\
            Make sure your sdr is connected.", 'offair-audiolog')
            self.process = None
        else:
            self.ffmpeg = subprocess.Popen(['ffmpeg', '-f', 's16le', '-ar', '8000', '-i', '-', '-acodec', 'libmp3lame', '-ab', icecast_bitrate + 'k', '-ac', '1', '-content_type', 'audio/mpeg', '-f', 'mp3',
            'icecast://source:{0}@{1}/{2}'.format(icecast_password, icecast_location, icecast_mountpoint)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            if self.ffmpeg.poll() != None:
                obplayer.Log.log("Could not start streaming off-air audio log.\n\
                Make sure your sdr is connected and that your icecast settings are entered.", 'offair-audiolog')
                self.ffmpeg = None

    def run(self):
        if self.process != None and self.ffmpeg != None:
            self._record_audio()

    def _record_audio(self):
        self.recording = True
        while self.recording:
            data = self.process.stdout.read(1)
            if data != b'':
                self.audio_data.append(data)
                self.ffmpeg.stdin.write(data)

    def get_audio(self):
        return b''.join(self.audio_data)

    def stop(self):
        self.recording = False
        data = self.get_audio()
        if self.process != None
            self.process.terminate()
        if self.ffmpeg != None
            self.ffmpeg.terminate()
        if data != b'':
            with wave.open(self.output_file, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(data)

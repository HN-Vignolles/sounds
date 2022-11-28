import time
import os
import subprocess
import uuid
import logging
from collections import deque
from struct import unpack
from pathlib import Path
from threading import Lock, Thread

import numpy as np
import pandas as pd
import soundfile as sf


log = logging.getLogger("recorder")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(filename)-14s:%(lineno)-4d %(levelname)-8s %(message)s",
    filename="recorder.log"
)
log.setLevel(logging.DEBUG)


df_columns = ['filename','target','category','fold']
pd.set_option('max_colwidth',None)
formats = {
    's16le':{
        'ffmpeg_str':'s16le',  # PCM signed 16-bit little-endian
        'bytes_per_sample':2,  # 16-bit
        'unpack':['<','h'],    # `<`: little endian, `h`: 2-byte integer; c.f. struct.unpack
        'dtype':'<i2',         # used by numpy.frombuffer
        'subtype':'PCM_16'     # used by soundfile.save
    }
}


class RecorderBase():
    def __init__(self,data_path,ffmpeg_path,input_format,
                 rec_duration=2,sample_rate=44100,output_format='s16le'):

        if not input_format:
            raise ValueError("input format must be supplied")
        if not data_path:
            raise ValueError("data_path must be supplied")
        if output_format not in ['s16le']:
            # TODO: add 'f32le'
            raise ValueError(f"{output_format} not implemented yet")

        self._rec_duration = rec_duration
        self._sample_rate = sample_rate
        self._recording = False

        self._bytes_per_sample = formats[output_format]['bytes_per_sample']
        self._ffmpeg_str = formats[output_format]['ffmpeg_str']
        self._dtype = formats[output_format]['dtype']
        self._subtype = formats[output_format]['subtype']
        self._chunk_size = 100
        self._unpack_str = self._get_unpack_str()
        self._ffmpeg_path = ffmpeg_path

        len = self._rec_duration * self._sample_rate
        out_buff_size = ((self._sample_rate * self._bytes_per_sample)
                         // self._chunk_size)
        self._total_bytes = 0

        # `_circ_buff` holds last `rec_duration` of captured audio
        self._circ_buff = deque(maxlen=len * self._bytes_per_sample)

        # queue, to send chunks of `chunk_size//2`
        # to display captured audio in 'roll mode'
        self._out_buff = deque(maxlen=out_buff_size*2)   # 2: safe margin

        # array x (coordinates) for plotting the waveform:
        self.x = np.linspace(0,self._rec_duration,len).tolist()

        self._input_fmt = input_format

        self._ffmpeg_stderr = None
        self._lock = Lock()
        self.data_path = Path(data_path)
        self.df_csv = self.data_path / 'samples.csv'
        if not self.df_csv.exists():
            df = pd.DataFrame(columns=df_columns)
            df.to_csv(self.df_csv,index=False)

        log.info(f"data path: '{data_path}'")
        log.info(f"ffmpeg binary path: '{ffmpeg_path}'")
        log.info(f"input format: '{input_format}'")
        log.info(f"recording duration: {rec_duration}")
        log.info(f"sample rate: {sample_rate}")
        log.info(f"output format: '{output_format}'")

    def _get_unpack_str(self):
        """get the unpack string used by `struct.unpack()` e.g. if
        we read chunks of 100 bytes from the ffmpeg output in little
        endian 16-bit format, the method `decoded_chunk` needs
        to decode 50 values of 2-bytes, using the string: `<50h`

        `<`: little endian; `h`: 2-byte integer"""
        unpack_str = (formats[self._ffmpeg_str]['unpack'][0]
                      + str(self.decoded_chunk_size)
                      + formats[self._ffmpeg_str]['unpack'][1])
        log.debug(f"unpack string: '{unpack_str}'")
        return unpack_str

    def start(self):
        """start recording"""
        if not self._recording:
            try:
                self._ffmpeg_stderr = open('ffmpeg.txt','w',encoding='utf-8')
                self._ffmpeg = subprocess.Popen(self._ffmpeg_cmd,
                                                stdout=subprocess.PIPE,
                                                stderr=self._ffmpeg_stderr)
            except Exception as e:
                log.exception(e)
                self._ffmpeg_stderr.close()
                raise

            stdout_peek = self._ffmpeg.stdout.peek(10)
            if not stdout_peek:
                raise RuntimeError("ffmpeg cmd doesn't return any data")
            self._recording = True
            log.info("ffmpeg process started")
            self._start_reader()

    def _start_reader(self):
        self._reader_thread = Thread(target=self._reader,args=())
        self._reader_thread.daemon = True
        self._reader_thread.start()

    def _reader(self):
        """reader thread for reading from the
        ffmpeg stdout into a deque"""
        self._reader_start_t = time.time()
        try:
            while self._recording:
                # self._lock.acquire()
                data = self._ffmpeg.stdout.read(self._chunk_size)
                self._total_bytes += self._chunk_size
                self._circ_buff.extend(data)
                self._out_buff.append(data)
                # self._lock.release()

        except Exception as e:
            log.error(f"reader error: {e}")

    def cancel(self):
        """stop recording without saving (backend)"""
        if self._recording:
            self._recording = False
            self._total_bytes = 0
            self._ffmpeg.kill()
            self._ffmpeg_stderr.close()
            self._reader_thread.join()

    @property
    def np_circ_buff(self):
        """returns the content of the circular buffer as a 1D numpy array"""
        np_array = np.frombuffer(bytes(self._circ_buff),dtype=self._dtype)
        return np_array

    @property
    def decoded_chunk(self):
        # self._lock.acquire()
        try:
            return unpack(self._unpack_str,self._out_buff.popleft())
        except Exception:
            return None
        # self._lock.release()

    @property
    def decoded_chunk_size(self):
        """The output from ffmpeg is inserted into the recording
        buffer (circular) in chunks of `_chunk_size`, and in turn
        placed in an output queue for plotting purposes.
        This value is the size of the already decoded chunks,
        e.g. 50 in case of `s16le` format, `chunk_size=100` bytes"""
        return self._chunk_size//self._bytes_per_sample

    @property
    def xy_buff(self):
        """return two lists corresponding
        to the X and Y coordinates of the waveform"""
        np_array = self.np_circ_buff
        return self.x,np_array.flatten().tolist()

    @property
    def atr(self):
        """average transfer rate"""
        # the average transfer rate should be:
        # 31.2KiB/s @`sample_rate=16000;s16le`
        # 86.1KiB/s @`sample_rate=44100;s16le`
        if self._recording:
            delta_t = time.time() - self._reader_start_t
            return round((self._total_bytes/delta_t)/1024,2)
        else:
            return 0

    def save(self,name:str,fold):
        """stop recording and save

        if `name` starts with `_`, a unique id is not added (`uuid4`).
        In this case, successive recordings are overwritten, and the
        filename is not added to the dataframe"""
        if self._recording:
            self._recording = False
            self._ffmpeg.kill()
            self._ffmpeg_stderr.close()
            np_sample = self.np_circ_buff
            if not name.startswith('_'):
                filename = f'{name}-{uuid.uuid4()}.wav'
                df = pd.read_csv(self.df_csv)
                s = pd.Series([filename,-1,name,fold],index=df_columns)
                df = pd.concat([df, s.to_frame().T])
                df.to_csv(self.df_csv,index=False)
            else:
                filename = f'{name}.wav'
            sf.write(self.data_path / filename,
                     np_sample,
                     samplerate=self._sample_rate,
                     subtype=self._subtype)
            log.info(f"{filename} saved")
            return filename

    def query_devices(self):
        """query source devices"""

    def setDevice(self,device):
        """set input device"""

    def is_recording(self):
        return self._recording


if os.name == 'posix':
    class Recorder(RecorderBase):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def query_devices(self):
            if self._input_fmt == 'pulse':
                import pulsectl
                pulse = pulsectl.Pulse('client')
                sources = pulse.source_list()
                s_dict = [{'index':str(source.index),
                           'input_dev':str(source.index),
                           'name':source.proplist['alsa.long_card_name']} for source in sources]
                pulse.close()
                log.debug(f"devices: {s_dict}")
                return s_dict

            elif self._input_fmt == 'alsa':
                import re
                arecordl = subprocess.Popen(['arecord','-l'], stdout=subprocess.PIPE)
                s_dict = []
                index = 0
                re_str = r'card ([0-9]+).*?\[([^\]]*)].*?device ([0-9]+).*?\[([^\]]*)]'
                for line in arecordl.stdout.readlines():
                    s = re.match(re_str,line.decode('utf-8'), re.IGNORECASE)
                    if s:
                        s_dict.append({'index':f'{index}',
                                       'input_dev':f'hw:{s.group(1)},{s.group(3)}',
                                       'name':f'{s.group(2)} - {s.group(4)}'})
                        index += 1
                log.debug(f"devices: {s_dict}")
                return s_dict

            elif self._input_fmt == 'lavfi':
                s_dict = [{'index':'1',
                           'input_dev':'sine=frequency=440',
                           'name':'A440'}]
                log.debug(f"devices: {s_dict}")
                return s_dict

            else:
                raise NotImplementedError

        def setDevice(self,device):
            self._input_dev_str = f"-f {self._input_fmt} -ac 1 -i {device}"
            self._ffmpeg_cmd = f"{self._ffmpeg_path} -re {self._input_dev_str} \
                                -ar {self._sample_rate} -ac 1 \
                                -f {self._ffmpeg_str} -blocksize 1000 \
                                -flush_packets 1 -".split()
            log.debug(f"ffmpeg command string: '{' '.join(self._ffmpeg_cmd)}'")


if os.name == 'nt':
    class Recorder(RecorderBase):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def query_devices(self):
            if self._input_fmt == 'dshow':
                import re
                ffmpegld = subprocess.Popen(['ffmpeg','-hide_banner','-list_devices','true',
                                         '-f','dshow','-i','dummy'], stderr=subprocess.PIPE)
                """
                Example output:
                [dshow @ 000002a830333c00] "Microphone (Webcam C170)" (audio)
                [dshow @ 000002a830333c00]   Alternative name "@device_cm_{33...A2}"
                [dshow @ 000002a830333c00] "Stereo Mix (Realtek(R) Audio)" (audio)
                [dshow @ 000002a830333c00]   Alternative name "@device_cm_{33...8D}"
                """
                s_dict = []
                index = 0
                name = ''
                re_str1 = r'\[dshow @ [A-Za-z0-9]+] "([^"]*)" \(audio\)'
                re_str2 = r'\[dshow @ [A-Za-z0-9]+].*?Alt.*?"([^"]*)'
                l1_match = False
                for line in ffmpegld.stderr.readlines():
                    l1 = re.match(re_str1,line.decode('ascii'),re.IGNORECASE)
                    l2 = re.match(re_str2,line.decode('ascii'),re.IGNORECASE)
                    if l1:
                        name = l1.group(1)
                        l1_match = True
                        continue
                    if l1_match and l2:
                        input_dev = f'audio="{l2.group(1)}"'
                        s_dict.append({
                            'index':str(index),
                            'input_dev':input_dev,
                            'name':name
                        })
                        index += 1
                log.debug(f"devices: {s_dict}")
                ffmpegld.kill()
                return s_dict

            elif self._input_fmt == 'lavfi':
                s_dict = [{
                    'index':'1',
                    'input_dev':'sine=frequency=440',
                    'name':'A440'
                }]
                log.debug(f"devices: {s_dict}")
                return s_dict

            else:
                raise NotImplementedError

        def setDevice(self,device):
            import shlex
            self._input_device = device
            # Update ffmpeg args:
            ffmpeg_cmd = f'{self._ffmpeg_path} -re \
                           -f {self._input_fmt} -ac 1 -i {device} -ar {self._sample_rate} -ac 1 \
                           -f {self._ffmpeg_str} -blocksize 1000 -flush_packets 1 -'
            self._ffmpeg_cmd = shlex.split(ffmpeg_cmd)
            log.debug(f"ffmpeg command string: {' '.join(self._ffmpeg_cmd)}")


if __name__ == "__main__":
    rec = Recorder('./datasets',{'format':'pulse','device':1})
    # code.interact(local=dict(globals(),**locals()))
    # print(rec.query_devices())
    rec.start()
    while True:
        try:
            out = rec._out_buff.popleft()
            # sys.stdout.buffer.write(out)
        except Exception:
            pass

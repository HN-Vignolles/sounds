import code
import sys
import time
import os
import subprocess
import uuid
from collections import deque
from struct import unpack
from pathlib import Path
from threading import Lock, Thread

import numpy as np
import pandas as pd
import soundfile as sf


df_columns = ['filename','target','category','fold']
pd.set_option('max_colwidth',None)
formats = {
    's16le':{'bytes_per_sample':2,'ffmpeg_str':'s16le','unpack':['<','h']}
}


class RecorderBase():
    def __init__(self,rec_duration,sample_rate):
        self._rec_duration = rec_duration
        self._sample_rate = sample_rate
        self._recording = False

    def _start_reader(self):
        self._reader_thread = Thread(target=self._reader,args=())
        self._reader_thread.daemon = True
        self._reader_thread.start()

    def start(self):
        """start recording"""

    def cancel(self):
        """stop recording without saving (backend)"""

    def _reader(self):
        """reader thread for reading from the
        ffmpeg stdout into a deque"""

    def query_devices(self):
        """query source devices"""

    def setDevice(self,device):
        """set input device"""

    def is_recording(self):
        return self._recording


class Recorder(RecorderBase):
    def __init__(self,data_path,input_format,
                 rec_duration=2,sample_rate=44100,output_format='s16le'):
        super().__init__(rec_duration,sample_rate)

        if not input_format:
            raise ValueError("input format must be supplied")
        if not data_path:
            raise ValueError("data_path must be supplied")
        if output_format not in ['s16le']:
            # TODO: add 'f32le'
            raise ValueError(f"{output_format} not implemented yet")

        self._bytes_per_sample = formats[output_format]['bytes_per_sample']
        self._ffmpeg_str = formats[output_format]['ffmpeg_str']
        self._chunk_size = 100
        self._unpack_str = self._get_unpack_str()

        len = self._rec_duration * self._sample_rate
        out_buff_size = ((self._sample_rate * self._bytes_per_sample)
                         // self._chunk_size)
        self._total_bytes = 0

        # `_circ_buff` holds last `rec_duration` of captured audio
        self._circ_buff = deque(maxlen=len * self._bytes_per_sample)

        """queue, to send chunks of `chunk_size//2`
        to display captured audio in 'roll mode'"""
        self._out_buff = deque(maxlen=out_buff_size*2)   # 2: safe margin

        # array x (coordinates) for plotting the waveform:
        self.x = np.linspace(0,self._rec_duration,len).tolist()

        self._input_fmt = input_format

        self._lock = Lock()
        self.data_path = Path(data_path)
        self.df_csv = self.data_path / 'samples.csv'
        if not self.df_csv.exists():
            df = pd.DataFrame(columns=df_columns)
            df.to_csv(self.df_csv,index=False)

    def query_devices(self):
        if self._input_fmt == 'pulse':
            import pulsectl
            pulse = pulsectl.Pulse('client')
            sources = pulse.source_list()
            s_dict = [{'index':str(source.index),
                       'input_dev':str(source.index),
                       'name':source.proplist['alsa.long_card_name']} for source in sources]
            pulse.close()
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
            return s_dict
        elif self._input_fmt == 'lavfi':
            return [{'index':'1',
                     'input_dev':'sine=frequency=440',
                     'name':'A440'}]
        else:
            raise NotImplementedError

    def setDevice(self,device):
        self._input_dev_str = f"-f {self._input_fmt} -ac 1 -i {device}"
        self._ffmpeg_cmd = f"/usr/bin/ffmpeg -re {self._input_dev_str} \
                            -ar {self._sample_rate} -ac 1 \
                            -f {self._ffmpeg_str} -blocksize 1000 \
                            -flush_packets 1 -".split()

    def start(self):
        if not self._recording:
            try:
                self._ffmpeg = subprocess.Popen(self._ffmpeg_cmd,
                                                stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL)
            except Exception:
                raise

            stdout_peek = self._ffmpeg.stdout.peek(10)
            if not stdout_peek:
                raise RuntimeError("ffmpeg cmd doesn't return any data")
            self._recording = True
            self._start_reader()
            # self._start_stderr_reader()

    def _start_stderr_reader(self):
        self._stderr_thread = Thread(target=self._stderr_reader,args=())
        self._stderr_thread.daemon = True
        self._stderr_thread.start()

    def _stderr_reader(self):
        try:
            while self._recording:
                b = self._ffmpeg.stderr.read(100)
                if b:
                    print(b.decode('utf-8'))
        except Exception as e:
            print('stderr_reader: ',e)

    def _reader(self):
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
            print(e)

    def cancel(self):
        if self._recording:
            self._recording = False
            self._total_bytes = 0
            self._ffmpeg.kill()
            self._reader_thread.join()
            # self._stderr_thread.join()

    def _get_unpack_str(self):
        """get the unpack string used by `struct.unpack()` e.g. if
        we read chunks of 100 bytes from the ffmpeg output in little
        endian 16-bit format, the method `decoded_chunk` needs
        to decode 50 values of 2-bytes, using the string: `<50h`

        `<`: little endian; `h`: 2-byte integer"""
        return (formats[self._ffmpeg_str]['unpack'][0]
                + str(self.decoded_chunk_size)
                + formats[self._ffmpeg_str]['unpack'][1])

    @property
    def np_circ_buff(self):
        """returns the content of the circular buffer as a 1D numpy array"""
        # '<i2': little endian 16-bit integer
        np_array = np.frombuffer(bytes(self._circ_buff),dtype='<i2')
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
                     subtype='PCM_16')
            return filename


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

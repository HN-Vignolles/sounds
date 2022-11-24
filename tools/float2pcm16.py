import soundfile as sf
from pathlib import Path
from tqdm import tqdm

converted_path = Path('./converted')
if not converted_path.exists():
    converted_path.mkdir()

wav_files = [str(i) for i in Path('./').glob('*.wav')]

for wav in tqdm(wav_files):
    data, samplerate = sf.read(wav)
    sf.write(converted_path / wav, data, samplerate, subtype='PCM_16')

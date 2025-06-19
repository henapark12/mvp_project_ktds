import io
import re
import json
import difflib
import isodate
from pydub import AudioSegment
from datetime import timedelta

MAX_SIZE_MB = 15  # gpt-4o-transcribe API 호출 시 안전한 wav 청크 최대 크기(MB)
CHUNK_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
OVERLAP_SEC = 0  # 청크간 문맥 연결을 위해 앞뒤로 겹칠 길이(초), 현재 사용 안 함

# ISO8601 문자열(예: PT5.32S)을 초(float)로 변환
def iso_to_sec(iso: str) -> float:
    return isodate.parse_duration(iso).total_seconds()

# 초(float)를 "hh:mm:ss.ms" 문자열로 변환
def fmt(sec: float) -> str:
    td = timedelta(seconds=sec).total_seconds()
    hours, remainder = divmod(td, 3600)
    minutes, sec = divmod(remainder, 60)
    ms = int((sec % 1) * 100)
    return f"{int(hours):02}:{int(minutes):02}:{int(sec):02}.{ms:02}"

# "[시:분:초.밀리]" 형태의 문자열에서 시간을 초(float)로 파싱
def parse_time(s):
    m = re.search(r'\[\((\d{2}):(\d{2}):(\d{2})\.(\d{2})\)\]', s)
    if not m:
        return None
    h, m_, s_, ms = map(int, m.groups())
    return h * 3600 + m_ * 60 + s_ + ms / 100

# wav 파일을 지정한 크기(바이트) 단위로 청크 분할
def chunk_wav_bytes(wav_bytes, rate=16000, chunk_bytes=CHUNK_SIZE_BYTES):
    audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    total_ms = len(audio)
    chunk_ms = int(chunk_bytes / (rate * 2) * 1000)
    chunks = []
    start = 0
    while start < total_ms:
        end = min(start + chunk_ms, total_ms)
        chunk = audio[start:end]
        buf = io.BytesIO()
        chunk.export(buf, format="wav")
        chunks.append(buf.getvalue())
        if end == total_ms:
            break
        start = end
    return chunks

# wav 전체 길이 기준으로 각 청크의 시작/끝 오프셋 반환
def get_chunk_offsets(wav_bytes, chunk_bytes=CHUNK_SIZE_BYTES, overlap_sec=OVERLAP_SEC, rate=16000):
    audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    total_ms = len(audio)
    chunk_ms = int(chunk_bytes / (rate * 2) * 1000)
    overlap_ms = overlap_sec * 1000
    offsets = []
    start = 0
    while start < total_ms:
        end = min(start + chunk_ms, total_ms)
        offsets.append((start / 1000, end / 1000))
        if end == total_ms:
            break
        start = end - overlap_ms
    return offsets

# 배치 전사 스크립트(txt)를 청크별 구간으로 나누기
def split_batch_script_by_chunks(batch_txt, chunk_offsets):
    import re
    def parse_times(line):
        m = re.search(r'\[\((\d{2}):(\d{2}):(\d{2})\.(\d{2})\)\]', line)
        m2 = re.search(r'\[(\d+\.\d+) s,', line)
        if not m or not m2:
            return None, None, line
        h, mi, s, ms = map(int, m.groups())
        offset = h*3600 + mi*60 + s + ms/100
        dur = float(m2.group(1))
        return offset, offset+dur, line

    lines = batch_txt.splitlines()
    lines_with_times = [parse_times(line) for line in lines if parse_time(line) is not None]
    chunk_texts = []
    for start, end in chunk_offsets:
        chunk_lines = [l for s, e, l in lines_with_times if s is not None and e is not None and (s < end and e > start)]
        chunk_texts.append('\n'.join(chunk_lines))
    return chunk_texts

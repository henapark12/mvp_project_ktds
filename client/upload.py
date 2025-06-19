import io
import json
from azure.storage.blob import ContentSettings
from utils import human_filesize
import soundfile as sf

def get_wav_metadata(wav_bytes):
    """
        WAV 파일 메타 추출
    """
    buffer = io.BytesIO(wav_bytes)
    with sf.SoundFile(buffer) as f:
        samplerate = f.samplerate
        duration = f.frames / samplerate
    size_bytes = len(wav_bytes)
    return {
        "samplerate": samplerate,
        "duration_sec": duration,
        "size_MB": round(size_bytes / (1024 * 1024), 2)
    }

def upload_blob(blob_service, container_name, blob_name, data_bytes, content_type=None):
    """
        wav파일 청킹해서 blob 업로드
    
    """
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
    block_size = 4 * 1024 * 1024
    uploaded = 0
    stream = io.BytesIO(data_bytes)
    block_ids = []
    while True:
        chunk = stream.read(block_size)
        if not chunk: break
        block_id = f"{len(block_ids):08d}".encode("utf-8")
        blob_client.stage_block(block_id, chunk)
        block_ids.append(block_id)
        uploaded += len(chunk)
        print(f"\r[UPLOAD] {human_filesize(uploaded)}", end="")
    blob_client.commit_block_list(block_ids, content_settings=ContentSettings(content_type=content_type))
    print("\n[OK] 업로드 완료")

def upload_to_blob(wav_bytes, meeting_obj, blob_service, container_name, meeting_dir):
    """
        녹음된 WAV 파일 및 회의 메타데이터 blob에 업로드
    """
    wav_name = f"{meeting_dir}/meeting_audio_raw.wav"
    json_name = f"{meeting_dir}/meeting_metadata.json"
    upload_blob(blob_service, container_name, wav_name, wav_bytes, content_type='audio/wav')
    meeting_obj['wav_metadata'] = get_wav_metadata(wav_bytes)
    json_bytes = json.dumps(meeting_obj, ensure_ascii=False, indent=2).encode('utf-8')
    upload_blob(blob_service, container_name, json_name, json_bytes, content_type='application/json')

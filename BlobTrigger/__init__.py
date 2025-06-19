import os
import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import json
from .stt_utils import stt_gpt4otranscribe, stt_batch, merge, summarize

def main(blob: func.InputStream):
    blob_path = blob.name
    container_name = os.environ.get("BLOB_CONTAINER_NAME", "meeting")
    wav_bytes = blob.read()
    logging.info(f"[BlobTrigger] New blob: {blob_path}, size={blob.length}")
    meeting_dir = os.path.dirname(blob_path)

    if meeting_dir.startswith(f"{container_name}/"):
        meeting_dir = os.path.relpath(meeting_dir, container_name)

    try:
        blob_service = BlobServiceClient(
            account_url=f"https://{os.environ['BLOB_ACCOUNT_NAME']}.blob.core.windows.net",
            credential=os.environ["BLOB_ACCOUNT_KEY"]
        )

        # gpt4otranscribe 전사 -> script_gpt4otranscribe.txt [1]
        stt_gpt4otranscribe(meeting_dir=meeting_dir, blob_service=blob_service, container_name=container_name) ###test

        meta_blob_path = f"{meeting_dir}/meeting_metadata.json"
        meta_blob_client = blob_service.get_blob_client(container=container_name, blob=meta_blob_path)
        meta_json = json.loads(meta_blob_client.download_blob().readall())
        num_participants = int(meta_json.get('num_participants', 5))
        meeting_id = os.path.basename(meeting_dir)
        wav_blob_path = f"{meeting_dir}/meeting_audio_raw.wav"
        
        # batch transcription 전사 -> script_batch_extracted.txt [2]
        stt_batch(meeting_id=meeting_id, wav_blob_path=wav_blob_path, max_num_speakers=num_participants) ###test

        # [1] + [2] -> script_final.txt [3]
        merge(meeting_dir, blob_service, container_name)

        # [3] 요약 -> summary.txt
        summarize(meeting_dir, blob_service, container_name) ###test

        logging.info(f"[BlobTrigger] 후처리 실행 완료: {meeting_dir} (참가자수: {num_participants})")

    except Exception as e:
        logging.error(f"[BlobTrigger] 처리 중 오류 발생: {e}")

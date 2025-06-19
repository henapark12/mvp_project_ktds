import os
import io
import json
import time
import httpx
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

from openai import AzureOpenAI
from azure.storage.blob import generate_blob_sas, BlobSasPermissions, BlobServiceClient

from .audio_processing import (
    chunk_wav_bytes, get_chunk_offsets,
    split_batch_script_by_chunks, iso_to_sec, fmt, MAX_SIZE_MB
)
from .blob_utils import get_prompt_from_blob, upload_blob

# gpt-4o-transcribe로 오디오 파일 한 개 전사 요청
def call_gpt4otranscribe(wav_bytes, phrase_str="", gpt_model="gpt-4o-transcribe"):
    client = AzureOpenAI(
        azure_endpoint=os.environ["OPENAI_ENDPOINT_URI"],
        api_key=os.environ["OPENAI_ENDPOINT_KEY"],
        api_version="2025-03-01-preview",
        http_client=httpx.Client(verify=False)
    )
    file_obj = io.BytesIO(wav_bytes)
    file_tuple = ("audio.wav", file_obj, "audio/wav")
    rsp = client.audio.transcriptions.create(
        file=file_tuple,
        model=gpt_model,
        response_format="json",
        prompt=phrase_str,
        language="ko",
        temperature=0.2,
    )
    return rsp.to_dict()

# 파일 크기에 따라 gpt-4o-transcribe 전체/청크별 전사 & blob 업로드
def stt_gpt4otranscribe(meeting_dir, blob_service, container_name):
    try:
        meta_blob_path = f"{meeting_dir}/meeting_metadata.json"
        meta_blob = blob_service.get_blob_client(container=container_name, blob=meta_blob_path)
        meta_data = json.loads(meta_blob.download_blob().readall())

        wav_blob_path = f"{meeting_dir}/meeting_audio_raw.wav"
        wav_blob = blob_service.get_blob_client(container=container_name, blob=wav_blob_path)
        wav_bytes = wav_blob.download_blob().readall()

        file_size_mb = meta_data['wav_metadata']['size_MB']
        print(f"[INFO] wav 파일 크기: {file_size_mb:.2f} MB")

        # 15MB 이하면 한 번에 전사
        if file_size_mb <= MAX_SIZE_MB:
            print(f"[INFO] 파일 크기가 {file_size_mb:.2f}MB로 15MB 이하. 청킹없이 바로 전사.")
            result = call_gpt4otranscribe(wav_bytes)
            transcript_text = result.get("text", "")
            if not transcript_text.strip():
                print("[WARN] gpt-4o-transcribe 전사 결과가 비어있음!")
            blob_path = f"{meeting_dir}/script_gpt4otranscribe.txt"
            upload_blob(transcript_text, blob_path, blob_service, container_name)
            return

        # 15MB 초과면 WAV를 청킹하고 청크별로 순차 전사
        print("[INFO] 파일 크기가 15MB 초과. 청킹 및 청크별 전사 진행")
        chunks = chunk_wav_bytes(wav_bytes)
        prev_text = ""
        chunks_dir = f"{meeting_dir}/gpt4otranscribe_chunks"
        for i, chunk in enumerate(chunks):
            chunk_wav_blob = f"{chunks_dir}/meeting_audio_chunk_{i+1:03}.wav"
            upload_blob(chunk, chunk_wav_blob, blob_service, container_name)
            result = call_gpt4otranscribe(chunk, phrase_str=prev_text)
            txt = result.get("text", "")
            prev_text = txt[-300:] if txt else ""
            chunk_txt_blob = f"{chunks_dir}/meeting_audio_chunk_{i+1:03}.txt"
            upload_blob(txt, chunk_txt_blob, blob_service, container_name)
    except Exception as e:
        print(f"[ERROR] stt_gpt4otranscribe() 전사 실행 중 오류: {e}")

# Azure Batch Transcription으로 화자분리+전사 실행 및 결과 저장
def stt_batch(meeting_id, wav_blob_path, max_num_speakers=5):
    SPEECH_KEY = os.environ["SPEECH_KEY"]
    SPEECH_REGION = os.environ["SPEECH_REGION"]
    BLOB_ACCOUNT_NAME = os.environ["BLOB_ACCOUNT_NAME"]
    BLOB_ACCOUNT_KEY = os.environ["BLOB_ACCOUNT_KEY"]
    BLOB_CONTAINER_NAME = os.environ["BLOB_CONTAINER_NAME"]

    blob_service = BlobServiceClient(
        account_url=f"https://{BLOB_ACCOUNT_NAME}.blob.core.windows.net",
        credential=BLOB_ACCOUNT_KEY
    )
    audio_sas_token = generate_blob_sas(
        account_name=BLOB_ACCOUNT_NAME,
        container_name=BLOB_CONTAINER_NAME,
        blob_name=wav_blob_path,
        account_key=BLOB_ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1)
    )
    wav_sas_url = f"https://{BLOB_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}/{wav_blob_path}?{audio_sas_token}"
    blob_client = blob_service.get_blob_client(container=BLOB_CONTAINER_NAME, blob=wav_blob_path)
    if not blob_client.exists():
        print("ERROR: 오디오 파일이 존재하지 않습니다.", wav_blob_path)
        return

    api_root = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/json"
    }
    job_name = Path(wav_blob_path).stem
    job_body = {
        "displayName": job_name,
        "contentUrls": [wav_sas_url],
        "locale": "ko-KR",
        "properties": {
            "diarizationEnabled": True,
            "diarization": {"speakers": {"minCount": 2, "maxCount": max_num_speakers}},
            "segmentation": {"mode": "Time", "segmentationSilenceTimeoutMs": 7000}
        }
    }
    res = requests.post(f"{api_root}/transcriptions", headers=headers, json=job_body, verify=False)
    if not res.ok:
        print("[ERROR] Batch job 등록 실패", res.text)
        return
    tid = res.json()["self"].split("/")[-1]
    while True:
        status_resp = requests.get(f"{api_root}/transcriptions/{tid}", headers=headers, verify=False).json()
        status = status_resp.get("status")
        logging.info(f"[INFO] Batch STT 진행상태: {status}")
        if status in {"Succeeded", "Failed"}:
            break
        time.sleep(30)
    if status != "Succeeded":
        print(f"[ERROR] Batch STT 실패: {status_resp}")
        return
    files_resp = requests.get(f"{api_root}/transcriptions/{tid}/files", headers=headers, verify=False).json()
    values = files_resp.get("values", [])

    # json -> txt 변환 (포맷 통일)
    def json2txt_bytes(data_bytes):
        data = json.loads(data_bytes)
        lines = []
        for p in data.get("recognizedPhrases", []):
            t = fmt(iso_to_sec(p["offset"]))
            dur = iso_to_sec(p["duration"])
            best = p["nBest"][0]
            lines.append(f"[({t})] speaker-{p.get('speaker','?')} : {best['display'].strip()}  [{dur:.2f} s, {best['confidence']*100:.1f} %]")
        return "\n".join(lines)

    # 결과 파일(json/txt) blob에 업로드
    for f in values:
        url = f.get("links", {}).get("contentUrl")
        if not url or not f['name'].endswith('.json'):
            continue
        data = requests.get(url, verify=False).content
        meeting_dir = os.path.dirname(wav_blob_path)
        json_blob_path = f"{meeting_dir}/script_batch.json"
        txt_blob_path = f"{meeting_dir}/script_batch_extracted.txt"
        upload_blob(data, json_blob_path, blob_service, BLOB_CONTAINER_NAME)
        upload_blob(json2txt_bytes(data), txt_blob_path, blob_service, BLOB_CONTAINER_NAME)
        print(f"[OK] batch_script.json / script_batch_extracted.txt 저장 완료: {meeting_dir}")
        break

import re

# batch/gpt4otranscribe 청크별 스크립트를 LLM으로 병합, 최종 txt 저장 -> script_final.txt
def merge(meeting_dir, blob_service, container_name, gpt_model="gpt-4o"):
    # 오디오 청크 구간 구하기
    wav_blob_path = f"{meeting_dir}/meeting_audio_raw.wav"
    wav_bytes = blob_service.get_blob_client(container_name, wav_blob_path).download_blob().readall()
    chunk_offsets = get_chunk_offsets(wav_bytes)

    # 배치 전사 스크립트 청크별로 분할
    batch_txt_path = f"{meeting_dir}/script_batch_extracted.txt"
    batch_txt = blob_service.get_blob_client(container_name, batch_txt_path).download_blob().readall().decode("utf-8")
    batch_chunks = split_batch_script_by_chunks(batch_txt, chunk_offsets)

    # gpt-4o 청크 스크립트 정렬
    gpt_chunks_dir = f"{meeting_dir}/gpt4otranscribe_chunks"
    def chunk_sort_key(name):  # 청크 파일명에서 인덱스 추출
        m = re.search(r'chunk_(\d+)', name)
        return int(m.group(1)) if m else 0

    txt_blobs = sorted([
        b.name for b in blob_service.get_container_client(container_name).list_blobs(name_starts_with=gpt_chunks_dir)
        if b.name.endswith(".txt")
    ], key=chunk_sort_key)

    gpt_chunks = [
        blob_service.get_blob_client(container_name, name).download_blob().readall().decode("utf-8")
        for name in txt_blobs
    ]

    print(f"[DEBUG] batch_chunks={len(batch_chunks)}, gpt_chunks={len(gpt_chunks)}")
    if len(batch_chunks) != len(gpt_chunks):
        logging.warning(f"[WARN] 청크 개수 불일치: batch={len(batch_chunks)}, gpt={len(gpt_chunks)}")

    prompt_template = get_prompt_from_blob(blob_service, container_name, "prompt_merge.txt")

    # 각 청크 쌍을 LLM에게 병합 요청하여 최종 스크립트 생성
    client = AzureOpenAI(
        api_version="2025-01-01-preview",
        azure_endpoint=os.environ["OPENAI_ENDPOINT_URI"],
        api_key=os.environ["OPENAI_ENDPOINT_KEY"],
        http_client=httpx.Client(verify=False)
    )

    final_lines = []
    for i in range(len(batch_chunks)):
        btxt = batch_chunks[i].strip()
        gtxt = gpt_chunks[i].strip() if i < len(gpt_chunks) else ""
        if not btxt:
            continue  # 배치 청크가 빈 경우는 건너뜀
        if not gtxt:
            final_lines.append(btxt)  # gpt 청크가 없으면 배치 청크만 사용
            print(f"[DEBUG] gpt 청크 없음, batch 청크 그대로 사용 (i={i})")
            continue
        prompt = prompt_template.format(txt1=btxt, txt2=gtxt)
        logging.info(f"[INFO] 병합 요청: 청크 {i+1}/{len(batch_chunks)}")
        rsp = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": "[병합 규칙]에 따라 txt1의 전사문을 txt2의 문장으로 교체하세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.25  # LLM의 결과 변동성 최소화
        )
        merged_chunk = rsp.choices[0].message.content.strip()
        final_lines.append(merged_chunk)

    # 최종 스크립트 파일 저장
    final_script = "\n".join(final_lines).strip()
    final_script_path = f"{meeting_dir}/script_final.txt"
    upload_blob(final_script, final_script_path, blob_service, container_name)
    print(f"[OK] script_final.txt 저장 완료: {final_script_path}")


# 최종 스크립트 파일로 회의 요약 생성 및 저장 --> summary.txt
def summarize(meeting_dir, blob_service, container_name, gpt_model="gpt-4o"):
    final_script_blob = f"{meeting_dir}/script_final.txt"
    summary_blob = f"{meeting_dir}/summary.txt"

    try:
        final_script = blob_service.get_blob_client(container=container_name, blob=final_script_blob).download_blob().readall().decode("utf-8")
        if not final_script.strip():
            print("[WARN] script_final.txt가 비어있음 -> summary를 생성불가")
            return

        prompt = get_prompt_from_blob(blob_service, container_name, "prompt_summarize.txt")

        client = AzureOpenAI(
            api_version="2025-01-01-preview",
            azure_endpoint=os.environ["OPENAI_ENDPOINT_URI"],
            api_key=os.environ["OPENAI_ENDPOINT_KEY"],
            http_client=httpx.Client(verify=False)
        )
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": final_script}
            ],
            temperature=0.2
        )
        summary = response.choices[0].message.content.strip()
        blob_service.get_blob_client(container=container_name, blob=summary_blob).upload_blob(summary.encode('utf-8'), overwrite=True)
        print(f"[OK] summary.txt 저장 완료: {summary_blob}")
    except Exception as e:
        print(f"[ERROR] summary 생성 중 에러: {e}")

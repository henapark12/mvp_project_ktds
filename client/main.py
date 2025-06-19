import time
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from utils import create_meeting_obj
from record import record_and_get_wav_bytes
from upload import upload_to_blob

BLOB_ACCOUNT_NAME = "aimeet"
BLOB_ACCOUNT_KEY = "6Vrfnw+Mdl6GF8z822vX8zerN8KS4BcnHl/7hy549Y9w6TzBNHZwcrPBGqarhFS8jCCRn3YdLvhB+AStddc3Dw=="
BLOB_CONTAINER_NAME = "meeting"

if __name__ == "__main__":
    
    print("안녕하세요, AI Meeting Agent 입니다.", flush=True) # pyinstaller문제(input() 바로 안뜨는문제) 해결
    time.sleep(0.1)  
    resp = input("회의 녹음을 시작할까요? [Y/N]: ").strip().lower()
    if resp != "y":
        print("녹음 취소.. 곧 종료됩니다.", flush=True)
        time.sleep(3)
        exit(0)

    meeting_obj = create_meeting_obj()
    wav_bytes = record_and_get_wav_bytes()
    if not wav_bytes:
        print("데이터 없음."); time.sleep(2); exit(0)

    while True:
        try:
            n = int(input("\n정확한 화자분리를 위해 화자 수를 입력해주세요. (범위: 2~10명): ").strip())
            if 2 <= n <= 10:
                meeting_obj['num_participants'] = n
                break
        except ValueError:
            pass
        print("범위를 고려해 화자 수를 다시 입력해주세요.")

    if input("\n회의 녹음파일을 업로드할까요? 업로드시 스크립트와 요약문이 추출됩니다. [Y/N]: ").strip().lower() == "y":
        blob_service = BlobServiceClient(
            account_url=f"https://{BLOB_ACCOUNT_NAME}.blob.core.windows.net",
            credential=BLOB_ACCOUNT_KEY
        )
        meeting_dir = f"{datetime.now().strftime('%Y%m%d')}/{meeting_obj['id']}"
        upload_to_blob(wav_bytes, meeting_obj, blob_service, BLOB_CONTAINER_NAME, meeting_dir)
        print("파일 업로드 완료. 프로그램이 곧 종료됩니다.")
        time.sleep(2)
    else:
        print("저장 안 함. 프로그램이 곧 종료됩니다.")
        time.sleep(2)

# Pipeline

- **BlobTrigger/**: Azure Function(자동 전사/요약) 백엔드 코드
- **client/**: 로컬 음성녹음 및 업로드 클라이언트

# Files

### 클라이언트
   - 구성
      `client/main.py`
         : 녹음 시작 - 실시간 전사/화자분리(spacebar로 일시정지/녹음재개 토글링) - 녹음종료 - 참가자(발화자) 수 입력 - blob에 wav업로드   
      `client/utils.py`
         : 회의 메타데이터(참가자 명단, 호스트 이름, 회의 이름 등), 녹음 분당 진행바 출력, 업로드시 보여줄 녹음파일크기 계산 등  
      `client/record.py`
         : 사용자 디바이스에서 활성화된 오디오 입력장치 조회 및 택1, 800샘플마다 실시간 스트림전사요청  
      `client/upload.py`
         : 업로드 전 오디오파일의 메타데이터 추출, blob스토리지에 <회의 메타데이터(JSON) + 회의 녹음파일(wav)> 업로드
            - (ref.) 업로드 시 4메가 단위로 청킹하는 이유: 대용량 파일 한번에 업로드 BLOB에 못함.   

### 서버 
   - 동작: Azure Function App / BlobTrigger
   - 리소스명: aimeetingFunctionApp (aimeetingfunctionapp.azurewebsites.net)
   - 로그: 함수앱(aimeetingFunctionApp) 진입 > 좌측 '개요' 탭 > 중앙 하단 'BlobTrigger' 폴더 > '로그' 탭
   - 구성
      `BlobTrigger/__init__.py`
         : 클라이언트에서 wav업로드시 "Azure function app <BlobTrigger>" > gpt4otranscribe call > batch transcription call > 두 호출결과 병합 > 요약본 추출
      `BlobTrigger/audio_processing.py`
         : 오디오 청킹(15메가단위로), 전사결과 청킹 및 JSON2TXT변환 등
      `BlobTrigger/blob_utils.py`
         : blob스토리지에서 파일 R/W
      `BlobTrigger/stt_utils.py`
         : gpt4otranscribe, batch transcription, gpt4o API 호출

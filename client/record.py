import io
import time
import sys
import threading
import platform
import numpy as np
import sounddevice as sd
import soundfile as sf
from azure.cognitiveservices.speech import SpeechConfig, AudioConfig, ResultReason, PropertyId
from azure.cognitiveservices.speech.audio import AudioStreamFormat, PushAudioInputStream
from azure.cognitiveservices.speech import transcription as speechsdk_transcription
from utils import print_minute_progress

RATE = 16000
CHANNELS = 1
MAX_DURATION_HOURS = 2
MAX_DURATION_SECONDS = MAX_DURATION_HOURS * 60 * 60

SPEECH_KEY = "BFTxWwEp2hSxWM8JwEMXcjJ8A1NUEBBE7zoE0AUGnvNYFWqyGTvwJQQJ99BEAC3pKaRXJ3w3AAAYACOGgwE5"
SPEECH_REGION = "eastasia"

def list_and_choose_input_device():
    """
        사용 가능한 마이크 목록을 보여주고, 사용자입력으로 장치 번호를 선택받아 반환
    """
    devices = sd.query_devices()
    input_devices = []
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            try:
                with sd.InputStream(device=i, channels=1, samplerate=RATE):
                    input_devices.append((i, d))
            except Exception:
                continue
    if not input_devices:
        print()
        print("-"*70)
        print("[ERROR] 사용 가능한 마이크가 없습니다.")
        print("      [Windows 설정 > 시스템 > 소리] 경로에서 아래 두 가지를 확인하세요.")
        print("      (1) 오디오 입력장치 선택여부")
        print("      (2) \"마이크를 테스트하세요\"에서 마이크 활성화여부")
        print("-"*70)
        print("\n프로그램이 곧 자동으로 종료됩니다. 마이크 연결 후 다시 이용해주세요.")
        time.sleep(5)
        sys.exit(3)
    print("-"*70)
    print("사용 가능한 입력 디바이스 목록:")
    for idx, dev in input_devices:
        print(f"  [{idx}] {dev['name']}")
    print("-"*70)
    if len(input_devices) == 1:
        print(f"자동 선택됨: {input_devices[0][1]['name']}")
        return input_devices[0][0]
    while True:
        try:
            sel = input(f"마이크 디바이스 번호를 선택하세요. (현재 기본장치: {input_devices[0][0]}): ").strip()
            if not sel:
                return input_devices[0][0]
            sel_idx = int(sel)
            if sel_idx in [i for i, _ in input_devices]:
                return sel_idx
        except Exception:
            pass
        print("잘못된 입력입니다. 선택할 장치의 번호만 입력해주세요. (예: 1)")

def check_input_device_active(device_idx):
    """
        선택한 마이크 장치가 녹음 가능한지 테스트
    """
    try:
        with sd.InputStream(device=device_idx, channels=CHANNELS, samplerate=RATE):
            pass
        return True
    except Exception as e:
        print(f"[ERROR] 디바이스 사용 불가: {e}")
        return False

def realtime_from_push_stream(push_stream):
    """
        사운드 디바이스로 입력된 PCM오디오 PushAudioInputStream을 실시간으로 Azure Speech에 보내고, 
        인식 결과(화자분리포함) 실시간 출력

            - 사용자 발화를 실시간 스트림(PushAudio)을 통해 azure에 보내고 전사/화자분리 결과 바로 출력
    """
    cfg = SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    cfg.speech_recognition_language = "ko-KR"
    cfg.set_property(PropertyId.SpeechServiceResponse_DiarizeIntermediateResults, "true")
    audio_cfg = AudioConfig(stream=push_stream)
    transcriber = speechsdk_transcription.ConversationTranscriber(cfg, audio_cfg)
    stop_event = threading.Event()

    def on_transcribed(evt): 
        """
            azure에서 전사결과 받을때마다 호출되는 콜백함수.
                - RecognizedSpeech 상태면 '[화자번호] 전사 발화내용' 출력
        """
        r = evt.result
        if r.reason == ResultReason.RecognizedSpeech:
            speaker = getattr(r, "speaker_id", "Unknown")
            print(f"[{speaker}] {r.text.strip()}")

    transcriber.transcribed.connect(on_transcribed)
    transcriber.start_transcribing_async()
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        transcriber.stop_transcribing_async()

def pause_key_listener(paused_flag, stop_flag):
    """
        spacebar 입력을 감지해 일시정지/재개 토글, 종료 플래그 신호를 받으면 종료

            - 윈도우/맥 나눠서 감지
            - paused_flag : 메인스레드에서 녹음 콜백과 진행바(1분마다출력)에 상태 전달용플래그
            - stop_flag: 메인스레드에 녹음종료시 pause thread도 마무리용 플래그
    """
    if platform.system() == "Windows": # 윈도우
        import msvcrt
        while not stop_flag.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b' ':
                    if paused_flag.is_set():
                        paused_flag.clear() # clear() : 녹음 시작
                        print("[녹음 재개]") 
                    else:
                        paused_flag.set() # set() : 녹음 일시정지
                        print("[녹음 일시정지]")
            time.sleep(0.03)
    else: # 맥북용
        import select, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            while not stop_flag.is_set():
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    key = sys.stdin.read(1)
                    if key == " ":
                        if paused_flag.is_set():
                            paused_flag.clear()
                            print("[spacebar] 녹음 재개")
                        else:
                            paused_flag.set()
                            print("[spacebar] 녹음 일시정지")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def record_and_get_wav_bytes():
    """
        전체 녹음/전사 파이프라인의 핵심 함수.
            - 마이크 선택 → 실시간 전사/화자분리
            - spacebar로 일시정지/재개 (진행바와 실제 녹음 모두 일시정지)
            - ctrl+c로 녹음 중단, wav byte로 반환
            - pause 해제시 내부 버퍼 중복방지
    """
    device_idx = list_and_choose_input_device()
    if not check_input_device_active(device_idx):
        sys.exit(1)
    yn = input(f"\n{device_idx}번을 선택하셨습니다. 해당 장비로 녹음을 시작할까요? [Y/N]: ").strip().lower()
    if yn != "y":
        print("녹음 취소됨."); time.sleep(2); sys.exit(0)

    paused_flag = threading.Event()
    stop_flag = threading.Event()
    skip_next_callback = threading.Event()  # <-- pause 해제 직후 콜백 스킵용
    pause_thread = threading.Thread(target=pause_key_listener, args=(paused_flag, stop_flag), daemon=True)
    pause_thread.start()

    print("\n" + "-"*70)
    print("[주의사항]")
    print(" - 키 안내")
    print("      (1) 녹음 일시중지/재개 : spacebar(토글링)")
    print("      (2) 녹음 중지 : ctrl+c")
    print(" - 실시간 STT 서비스와 녹음파일 업로드를 위해 인터넷 연결상태를 확인해주세요.")
    print(" - 녹음이 안되는 경우,")
    print("      [Windows 설정 > 시스템 > 소리] 경로에서 아래 두 가지를 확인하세요.")
    print("      (1) 오디오 입력장치 선택여부")
    print("      (2) \"마이크를 테스트하세요\"에서 마이크 활성화여부")
    print("-"*70)

    rec_buffers = []
    fmt = AudioStreamFormat(samples_per_second=RATE, bits_per_sample=16, channels=CHANNELS)
    push_stream = PushAudioInputStream(fmt)
    trans_thread = threading.Thread(target=realtime_from_push_stream, args=(push_stream,), daemon=True)
    trans_thread.start()

    def audio_callback(indata, frames, t, status):
        """
            sounddevice InputStream 콜백에서 일시정지/녹음 buffer 관리, Azure 전송
        """
        if paused_flag.is_set():
            return
        if skip_next_callback.is_set():
            skip_next_callback.clear()
            return
        rec_buffers.append(indata.copy())
        push_stream.write(indata.tobytes())

    stream = sd.InputStream(
        samplerate=RATE, channels=CHANNELS, dtype='int16',
        callback=audio_callback,
        blocksize=800,  # 빠른 실시간 전사위해 800샘플마다 전송
        device=device_idx
    )

    t0 = time.time()
    total_pause_time = 0.0
    pause_start = None
    last_min = -1
    recorded_sec = 0.0

    try:
        stream.start()
        print("[녹음 시작] * spacebar: 일시정지/재개, ctrl+c: 종료/저장")
        while True:
            time.sleep(0.05)
            # 일시정지 시작
            if paused_flag.is_set() and pause_start is None:
                pause_start = time.time()
            # 일시정지 종료(녹음재개)
            if not paused_flag.is_set() and pause_start is not None:
                total_pause_time += time.time() - pause_start
                pause_start = None
                skip_next_callback.set()   # <--- pause 해제 후 첫 콜백은 indata 무시
            recorded_sec = time.time() - t0 - total_pause_time
            if not paused_flag.is_set():
                curr_min = int(recorded_sec // 60)
                if curr_min != last_min:
                    last_min = curr_min
                    print_minute_progress(recorded_sec)
            if recorded_sec > MAX_DURATION_SECONDS:
                break
    except KeyboardInterrupt:
        print("[ctrl+c] 녹음 중단")
    finally:
        stop_flag.set()      # pause thread 종료
        pause_thread.join()
        stream.stop()
        stream.close()
        push_stream.close()
        trans_thread.join(timeout=2)

    if not rec_buffers:
        print("녹음한 데이터가 없습니다.")
        return None
    audio = np.concatenate(rec_buffers, axis=0)
    buffer = io.BytesIO()
    sf.write(buffer, audio, RATE, format='WAV')
    buffer.seek(0)
    return buffer.getvalue()

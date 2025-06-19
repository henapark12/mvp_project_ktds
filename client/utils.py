import uuid
from datetime import datetime

def create_meeting_obj():
    """
        UUID 기반 회의ID와 메타데이터 생성 *****나중에 사용자입력받으면 대체할 부분*****
    """
    return {
        "id": f"{datetime.now().strftime('%Y%m%d_%H%M%S%f')}_{uuid.uuid4()}",
        "created_at": datetime.now().isoformat(),
        "participants": ['사회자', '이재명', '김문수', '이준석', '권영국'],
        "meeting_title": "Meeting AI Agent",
        "host": "사회자"
    }

def print_minute_progress(elapsed_sec, total_bars=120):
    """
        녹음현황을 막대 그래프로 출력
    """
    mins = elapsed_sec // 60
    curr_bars = min(int(mins), total_bars)
    percent = min((mins / total_bars) * 100, 100.0)
    bar_str = '[' + '■ ' * curr_bars + ']'
    print(f"\r{bar_str}  녹음 {mins}분 경과 (최대 2시간 중 {percent:5.2f}%)", end="\n", flush=True)


def human_filesize(nbytes):
    """
        바이트를 사람이읽기쉬운 단위로 변환. 녹음 종료후 해당파일 사이즈 출력.
    """
    for unit in ['B','KB','MB','GB','TB']:
        if nbytes < 1024.0:
            return f"{nbytes:.2f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.2f} PB"

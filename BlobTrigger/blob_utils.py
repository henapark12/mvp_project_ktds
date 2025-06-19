# blob에서 프롬프트(txt) 파일을 읽어옴
def get_prompt_from_blob(blob_service, container_name, prompt_filename):
    blob_client = blob_service.get_blob_client(container=container_name, blob=prompt_filename)
    return blob_client.download_blob().readall().decode("utf-8")

# 문자열 또는 바이너리 데이터를 blob에 저장 (데이터 비어있으면 skip)
def upload_blob(data, blob_path, blob_service, container_name, verbose=True):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data or (isinstance(data, bytes) and not data.strip()):
        if verbose:
            print(f"[WARN] 업로드 데이터가 비어있음: {blob_path}")
        return
    blob_service.get_blob_client(container=container_name, blob=blob_path).upload_blob(data, overwrite=True)
    if verbose:
        print(f"[OK] blob 저장: {blob_path}")

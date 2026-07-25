# inbox

카카오톡 '대화 내보내기'로 저장한 txt 를 이 폴더에 둔다.

```bash
python -m scripts.ingest_incremental --dry-run   # 확인
python -m scripts.ingest_incremental             # 반영
```

반영된 파일은 `inbox/processed/` 로 옮겨진다.
원본 대화가 담기므로 이 폴더는 커밋되지 않는다(.gitignore).

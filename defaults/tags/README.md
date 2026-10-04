# 태그 사전 / Tag dictionary

이미지 프롬프트를 쓸 때 태그 자동 완성과 "알 수 없는 태그·별칭" 표시에 쓰는 목록이다.
A tag list used for tag autocomplete and unknown-tag / alias hints when writing image prompts.

## 위치 / Location

| 언제 / When | 경로 / Path |
|---|---|
| 배포본 안의 원본 / Bundled original | `app/defaults/tags/danbooru.csv` |
| 앱이 쓰는 사본 / Copy the app uses | `<앱 폴더>/data/tags/danbooru.csv` (처음 실행 때 복사 / copied on first run) |
| 직접 추가하는 사전 / Your own lists | `<앱 폴더>/data/tags/<이름>.csv` |

`data/tags/`에 있는 CSV는 모두 사전으로 읽는다. 설정 → 이미지 → 태그 사전에서 가져오기·지우기를 할 수도 있다.
Every CSV in `data/tags/` is loaded. You can also add or remove lists in Settings → Image → Tag dictionary.

## 양식 / Format

UTF-8, 머리줄 없음, 한 줄에 태그 하나. / UTF-8, no header, one tag per line.

```csv
1girl,0,6860682,"1girls,sole_female"
long_hair,0,5200000,"long_hairs"
```

| 열 / Column | 뜻 / Meaning |
|---|---|
| 1 | 태그 이름(밑줄 표기) / tag name (underscores) |
| 2 | 분류 / category: `0` 일반 general, `1` 작가 artist, `3` 작품 copyright, `4` 캐릭터 character, `5` 메타 meta |
| 3 | 사용 수 / post count (자동 완성 순서 / autocomplete order) |
| 4 | 별칭, 쉼표로 구분해 큰따옴표로 감쌈(없으면 빈 칸) / aliases, comma-separated and quoted (may be empty) |

- 자동 완성은 사용 수가 많은 순서로 제안한다. 별칭으로 쳐도 대표 태그를 제안한다.
- 사전과 비교할 때만 표기를 맞춘다(소문자, 공백 ↔ 밑줄). 프롬프트에 저장하는 태그의 표기는 바꾸지 않는다.

## 출처 / Source

`danbooru.csv`는 [DraconicDragon/dbr-e621-lists-archive](https://github.com/DraconicDragon/dbr-e621-lists-archive)의
Danbooru 2025-09-01 목록이다([Unlicense](https://unlicense.org)). Danbooru의 태그를 스크립트로 모은 것이며, 성인 태그가 포함되어 있다.
`danbooru.csv` is the Danbooru 2025-09-01 list from the archive above (Unlicense). It is generated from Danbooru tags
and includes adult tags.

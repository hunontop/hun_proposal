# app/ — 엔진 (① generic, 노하우 0)

3계층 중 엔진. 색/패턴을 모름 — 노하우는 `packs/`에서 주입, 데이터는 `projects/`에서.

## 구성
- `schemas/` — JSON Schema 계약: `slide_model`(정본) + `stage6/7/8`(단계 출력)
- `slide_model.py` — 정본 로드·검증(`validate`)·단계간 slide_id 교차검증(`cross_validate`)
- `render/htmlgen.py` — **기본 HTML 렌더러**(자기완결). `render_html(deck, pack, out)`: 토큰→CSS변수, per-template 레이아웃 디스패치, 미지원→fallback+🔴, 외부의존 0. ★베이크오프 결정 채택.
- `render/dispatch.py` — PPTX 백엔드(선택). `Deck(pack).add(template_id, **fields)` / `add_specs`. python-pptx.
- `render/renderers.py` — PPTX용 generic 렌더러 레지스트리(골격).

## 인터페이스
```bash
# 기본: HTML 덱 (자기완결)
python app/render/htmlgen.py <deck.json> <pack> <out.html>
# 선택: PPTX 백엔드
python -c "from app.render.dispatch import add_specs; add_specs(deck, 'core', 'out.pptx')"
```
- `template_id` → 팩 templates.json의 `renderer` → REGISTRY. 없으면 role, 없으면 fallback+🔴.
- 토큰은 `packs/<name>/tokens.json`에서만. 하드코딩 금지.

## 상태
- M1: 스키마 + 디스패치 골격 완료.
- M3: **HTML 렌더러(htmlgen.py) 작동** — sample_deck → 자기완결 HTML 6슬라이드(외부의존0). 레이아웃 6종+fallback 구현, 나머지 템플릿 레이아웃은 점증.
- 검증: `python app/slide_model.py <deck.json> [schema_name]`

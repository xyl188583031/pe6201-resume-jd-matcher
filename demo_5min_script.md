# PE6201 — 5-minute demo: rundown + verbatim script

**Target: 5:00.** The teacher's brief says *"5 +/- 3 min"*, and *"If you check in a video
greater then 8 minutes, I will go through first max 8 min"*. Graded on **Precision,
Articulation, Succinctness**, with your face **and** the screen visible.

Layout of this file, so nothing is a surprise:

| Section | Language | Why |
|---|---|---|
| §1 Pre-flight | 中文 | 给你的操作说明，不是口播内容 |
| §2 Rundown (timeline) | **English only** | 逐字稿的一部分 |
| §3 Verbatim script | **English only** | 直接照读，不要改词 |
| §4 Recording checklist | 中文 | 录制前的检查项 |
| §5 What I verified | 中文 | 本文件里哪些数字是我实测的 |

Narration totals **599 words over 300 s ≈ 120 words/minute** — a natural demo pace with
room for clicking. If you run fast, the slack is in §3 SEG-3 (the live demo).

---

## 1 · Pre-flight（开录前，逐条做完）

### 1.1 ⚠️ 用对解释器 —— 这是最容易翻车的一步

本机 `python` 指向 WorkBuddy 托管解释器（3.13.12），**它没有 fastapi / torch / bs4**，
后端起不来。项目依赖装在**系统 Python 3.12**：

```bash
PY="C:/Users/xyl18/AppData/Local/Programs/Python/Python312/python.exe"
```

本文件下面所有命令都用 `"$PY"`。**不要用裸 `python`。**

### 1.2 准备两个终端（先起好，再按录制）

```bash
PY="C:/Users/xyl18/AppData/Local/Programs/Python/Python312/python.exe"
cd "D:/NTU/pe6201/individual project/resume_jd_matcher"

# 终端 A —— 后端（live：真调 gpt-4o-mini，读 .env）
"$PY" -m server.app --port 8765

# 终端 B —— 演示表单的静态服务
"$PY" -m http.server 8770 --bind 127.0.0.1 --directory demo
```

后端启动后会打印 token；token 也写在 `artifacts/server_token.txt`。
**备注**：若录制时网络不通，把终端 A 换成 `RJD_OFFLINE=1 "$PY" -m server.app --port 8765`
——界面完全一样，只是回答来自本地桩，口播里 SEG-4 的数字不受影响（那是交付运行的结果）。

### 1.3 加载扩展

1. 若 `extension/dist/` 不存在：`cd extension && npm install && npm run build`
2. 打开 `edge://extensions` → 开启开发者模式 → **加载解压缩的扩展** → 选 `resume_jd_matcher/extension/dist`
3. 卡片应显示版本 **0.3.0**，无红色 Errors

> **用 Edge，不要用品牌 Chrome。** Chrome 137 起接受 `--load-extension` 却静默忽略。
> 本步骤请**手动**在扩展页加载，不要用命令行。

### 1.4 确认端口空闲

```bash
for p in 8765 8770; do netstat -ano | grep -q ":$p .*LISTENING" && echo "$p BUSY" || echo "$p free"; done
```

端口上若已有**旧服务**，新进程会 bind 失败而**旧进程继续应答** `/health` —— 你会对着一个旧版本演示。
见到 `BUSY` 先杀掉再开。

### 1.5 演示素材（本轮新建，已在仓库里）

| 文件 | 用途 |
|---|---|
| `resume_jd_matcher/demo/demo_resume.pdf` | 1 页 PDF 简历，**给面板上传**。文本可被 PDF.js 提取（已验），内容是 `data/cases/cases.json` 里 `AIML-v01_sparse_terse-p00` 的同一份简历 —— 浏览器演示与 A/B/C 评估用的是同一个仪器 |
| `resume_jd_matcher/demo/demo_jd.txt` | **粘贴用**的 JD 文本（同一 case） |
| `resume_jd_matcher/demo/application_form.html` | 演示表单，26 个字段，永不提交 |

---

## 2 · Rundown

| # | Time | Dur | On screen | Beat | Words |
|---|---|---|---:|---|---:|
| SEG-0 | 0:00–0:20 | 20s | You + report cover (or straight to the form) | What it is, and the one thing it won't do | 45 |
| SEG-1 | 0:20–0:48 | 28s | `report_en.md §2–§3` | The problem, and one user | 63 |
| SEG-2 | 0:48–1:02 | 14s | Terminal A, then the browser | Two surfaces, one pipeline | 36 |
| SEG-3 | 1:02–2:52 | 110s | Live: backend → panel → form | The product, working | 210 |
| SEG-4 | 2:52–4:02 | 70s | `report/analyse_run.py` output | The evidence: A/B/C, abstention, fabrication | 138 |
| SEG-5 | 4:02–4:42 | 40s | Same output, scrolled to cost §7 | The uncomfortable finding | 70 |
| SEG-6 | 4:42–5:00 | 18s | Report §12 (limitations) | What stays unmeasured, and next | 37 |
| | | **300s** | | | **599** |

**Do not skip SEG-5.** The rubric explicitly asks for *"metrics performance critique"* and
*"evals critique"*. The B-beats-C result *is* the critique — a demo that only shows a
working prefill and a green number reads as unconvincing.

---

## 3 · Verbatim script

Read the **SAY** lines as written. `[SCREEN]` lines are stage directions — do not read them.

### SEG-0 · 0:00–0:20 · Hook

`[SCREEN]` Face + screen. Leave the application form visible behind you.

**SAY:**
> This is the Graduate Resume–JD Matcher. It takes a graduate's resume and a job
> posting, and it pre-fills a job application form, one field at a time. The one thing
> it refuses to do is invent experience. It declines instead — and it says why.

### SEG-1 · 0:20–0:48 · The problem

`[SCREEN]` Show `report/report_en.md` §2–§3 (the one-sentence problem and the persona).

**SAY:**
> The problem is narrow. Wei Ling is a master's student applying for her fourth
> internship of the week; she spends ten to fifteen hours a week on applications. The
> tools that exist either score her resume or rewrite it. None of them will say
> "I don't know" — and a fabricated line is a risk she carries into the interview, not
> the tool.

### SEG-2 · 0:48–1:02 · Two surfaces

`[SCREEN]` Cut to Terminal A (backend already running and printing its banner).

**SAY:**
> I built two surfaces: an evaluated pipeline with three conditions, and a browser
> assistant. The browser layer adds no new policy — it calls the same functions the
> evaluation calls, so the two cannot drift apart.

### SEG-3 · 1:02–2:52 · Live demo

`[SCREEN]` Terminal A: point at the startup banner.

**SAY:**
> The backend runs on loopback only: six routes, token-gated, with no write route and
> no submit route. That is a design decision, not an omission.

`[SCREEN]` Browser: `http://127.0.0.1:8770/application_form.html`

**SAY:**
> This is a simulated application form — twenty-six fields. It never submits anywhere.

`[SCREEN]` Click the toolbar icon once (this real click is what opens the side panel).
Paste the token from `artifacts/server_token.txt`. Tick the four module toggles.

**SAY:**
> Step one: authorise. These toggles decide what may leave the browser. Unticking one
> removes it before the request is assembled.

`[SCREEN]` Upload `demo/demo_resume.pdf`, then click to apply the returned profile.

**SAY:**
> Step two: the profile. I'll upload a PDF resume. PDF.js parses it inside the page —
> the file never leaves this machine, only the text crosses. Notice it asks me to apply
> the result, rather than quietly replacing what I typed.

`[SCREEN]` Click **Scan**.

**SAY:**
> Scan asks the page what it holds, and shows what it will skip.

`[SCREEN]` Paste `demo/demo_jd.txt` into the posting box, click **Analyze**.

**SAY:**
> Now the posting. Paste it, analyze. The useful output is not the match score — it's
> the requirements my profile does not evidence.

`[SCREEN]` Click **Generate**. Let the rows populate.

**SAY:**
> Generate: one row per field, each with its own confidence and its own reason. Below
> the threshold, a row is withheld with a reason instead of guessing.

`[SCREEN]` Scroll to the two identity rows at the bottom. Hover/point — no value, no Apply.

**SAY:**
> Watch these two rows: passport number, and national ID. No value, and no Apply. They
> are never collected, never generated, and never sent to the model.

`[SCREEN]` Apply one ordinary row (phone number). Show it land in the page control.

**SAY:**
> I'll apply the phone number. It lands in the page.

`[SCREEN]` Page console: `window.__submitAttempts` → still `0`.

**SAY:**
> And the form was never submitted — the counter is still zero.

### SEG-4 · 2:52–4:02 · The evidence

`[SCREEN]` Switch to the terminal and run:

```bash
cd "D:/NTU/pe6201/individual project"
"C:/Users/xyl18/AppData/Local/Programs/Python/Python312/python.exe" \
  report/analyse_run.py --artifacts resume_jd_matcher/artifacts/kbv2_final
```

Point at section 1 (the counts table) while you speak.

**SAY:**
> Now the evidence. I ran the whole pipeline over twenty cases and three conditions,
> live, on GPT-4o-mini. Condition A is the TF-IDF baseline — no model at all. B is
> prompt-only. C adds retrieval. The bar was sixteen of twenty. A scores twelve, B
> seventeen, C sixteen: B and C pass, A fails.
>
> But look at B against C. B beats C. The retrieval layer cost more and bought nothing —
> that was my kill condition, agreed before the pilot, and it fired.
>
> Abstention is two numbers, not one: how often, and whether those were the cases it
> would have got wrong. A abstained three times, and all three were cases it would have
> failed anyway. C abstained once, and that one was false — it declined on an easy case.
>
> Across all sixty records: zero fabricated skills.

### SEG-5 · 4:02–4:42 · The uncomfortable finding

`[SCREEN]` Scroll to section 7 of the same output — *Cost per SUCCESSFUL task*.

```text
B: total $0.0137 / 17 passed = $0.0008 per successful task
C: total $0.0154 / 16 passed = $0.0010 per successful task
```

**SAY:**
> The least comfortable finding is that the cheapest configuration was also the best.
> B costs eight-tenths of a cent per successful task; C costs one cent, is less accurate,
> and is about five hundred times slower than the rules path. I am not claiming retrieval
> does not work. I am claiming that on fifty-four chunks — small enough to fit in one
> retrieval call — it had nothing to add.

### SEG-6 · 4:42–5:00 · Limits and next

`[SCREEN]` Show the report's limitations section (`final_report_v8.md` §12).

**SAY:**
> Two things stay unmeasured: the time saving, which needs three independent timers, and
> a wider forty-case evaluation. Next I would build the router, and separate the corpus
> change from the embedder change, so the gain is attributed.

---

## 4 · 录制检查清单

- [ ] 用 `demo/application_form.html`（不是 `file://` —— manifest 只匹配 `http/https`，从磁盘打开会显示成扩展坏了）
- [ ] 工具栏图标**手动点一次**（合成手势打不开 side panel，这是设计限制）
- [ ] 面板设置里贴的是 `artifacts/server_token.txt` 里的 token
- [ ] 口播里出现的数字都能在屏幕上找到：26 字段 / 6 路由 / 12-17-16 / 16 门槛 / 3-0-1 弃答 / 60 记录 0 编造 / $0.0008 与 $0.0010 / 54 chunks
- [ ] **不要点 submit 或 reset**；`window.__submitAttempts` 必须仍是 `0`
- [ ] 别在录的时候跑 `run_form_matrix.py`（它会整体覆盖 `artifacts/form_matrix/report.md`）
- [ ] 时长 5±3 分钟；超过 8 分钟老师只看前 8 分钟
- [ ] 人脸与屏幕同时可见

---

## 5 · 本文件里的数字，我是怎么验证的

| 声明 | 验证方式 | 结果 |
|---|---|---|
| 后端能起、6 条路由、live_api | 用 Python312 真起服务，`/health` + `/openapi.json` | ✅ 路由恰为 `/scan` `/generate` `/jd/fetch` `/jd/analyze` `/extract_resume` `/health` |
| A/B/C = 12/17/16，门槛 16/20 | 真跑 `report/analyse_run.py`（重算自 `runs.jsonl`） | ✅ 输出见 SEG-4/SEG-5 |
| 弃答 3/0/1、0 编造、$0.0008/$0.0010、54 chunks | 同上，第 1/2/7/11 节 | ✅ 逐项对上 |
| 表单 26 字段、含 Passport 与 NRIC | 直接数 `demo/application_form.html` 的 `<label>` | ✅ 26 个，第 21/22 行即两个身份字段 |
| 身份字段没有值、不给 Apply | `scripts/e2e_check.py`（本机真跑） | ✅ **133/133 checks passed** |
| 浏览器层（面板渲染、注入、写入、不提交） | `bash extension/scripts/_run_browser_check.sh`（真 Edge） | ✅ **44/44 checks passed** |
| 上传的 PDF 可被解析 | 用 pypdf 抽 `demo_resume.pdf` 文本 | ✅ 1 页，姓名/邮箱/学校/PyTorch/Sentinel Data 全部命中 |
| 500× 更慢 | 来自 `analyse_run.py` §6 的中位延迟（16 ms vs 8,375 ms） | ✅ 约 520×，口播说"about five hundred" |
| `gpt-4o-mini` 这个型号名 | `/health` 返回 `mode: live_api, model: openai/gpt-4o-mini` | ✅ |

**规模与边界，如实说明：**

- 这份 5:00 是**设计时长**，不是我掐表录过的时长。逐字稿 599 词按 ~120 wpm 推算；真人演示
  会因点击与停顿变慢，正负 20 秒内属正常。
- 我**没有**录制过一遍，所以「念完正好 5 分钟」这一条我给不了保证。
- 我**没有**在面板里真人点击走完 SEG-3 的十步。已验证的是：服务端契约 133/133、
  真浏览器 44/44（含面板页面渲染与写入）、PDF 可解析。**「在 side panel 容器里真人点一遍」
  仍是只有你能做的那一步** —— 它恰好也是扩展 README 一直标为未验证的那一格，这个视频正好把它补上。
- `RJD_OFFLINE=1` 的后端我**没有**在浏览器里连过；上面 133/133 是离线桩跑的。
  录制建议用 live 后端（SEG-4 的数字本就来自 live 交付运行，不受影响）。

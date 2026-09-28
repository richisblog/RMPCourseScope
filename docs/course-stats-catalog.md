# CourseScope 课程目录与课程级统计

两个 SQLite 文件独立保存、按 `course_key` 精确连接：

- `uc_davis_rmp_normalized.sqlite`：用户评价、原始课程名、推断关联，以及 `course_professor_stats`。
- `ucdavis_catalog.sqlite`：UC Davis 官方学科目录和课程详情快照。`courses` 包含 `title_en`、`units`、`description`、`prerequisites`、`details_json`（含 `General Education` 分类）、完整 `raw_html`、原始链接与抓取时间；`subjects` 记录每个学科页。只从 `/courses-subject-code/` 页面收集，不批量请求 robots.txt 禁止的 `/search/` 或 `/ribbit/`。`/api/v1/catalog/courses/{key}` 将分类独立暴露为 `general_education`，课程页也显示官方分类和来源链接。

`course_professor_stats` 的主键为 `(course_key, professor_id)`；`stats_json` 是完整的统计对象，同时把常用指标展开成列，便于 SQL 排序。构建脚本 `scripts/build_course_stats.py` 可在新增评价后重新生成，`scripts/sync_catalog_titles.py` 把官方标题按完全一致的课程 key 同步到评价库的课程索引供搜索使用。学生乱写的 `course_raw` 始终原样保留；未匹配官方目录的异常 key 不会被猜改。

统计口径：一个 `(review_id, course_key)` 最多计一次，即使它存在多个关联理由。总体、最近 730 天、此前 730 天、逐日历年都给出评价数、有效评分数、均值、中位数、样本标准差、1–5 分计数、正面（≥4 分）与负面（≤2 分）比例、难度均值/中位数。正面比例提供 Wilson 95% 区间，但这**不能**消除自愿评价的选择偏差。趋势差值 = 最近 730 天均分 − 此前 730 天均分；两个窗口各至少 5 条有效评分才计算，绝对差 ≥0.3 标为 up/down，否则 stable。它不是显著性检验，也不意味着因果关系。缺少足够样本时是 `insufficient_data`，不能解释为“没有变化”。

AI 优先调用 JSON：

1. `GET /api/v1/search?q=MAT%2021C&type=course` 查课程 key；
2. `GET /api/v1/catalog/courses/MAT21C` 查官方课程资料及原始链接；
3. `GET /api/v1/courses/MAT21C/professors` 比较教授，读取 `course_stats`；
4. `GET /api/v1/courses/MAT21C/professors/{id}/stats` 读完整逐年统计；
5. 必要时 `GET /api/v1/professors/{id}/reviews?course=MAT21C` 阅读原文和关联置信度。

当列表使用 `min_confidence>0` 时，`course_stats` 为 `null`，因为预计算统计包含全部关联。不可把过滤后的 `linked_review_count` 与未过滤的均值混为同一口径；应阅读原始评价或用 SQL 按过滤条件重新计算。`overall_rating` 是教授跨课程档案均分，`course_stats.overall.rating_mean` 才是该课程的关联评价均分。所有数据仅作选课参考，不是官方成绩、开课记录、教职状态或对全体学生的无偏估计。

# experiments/

每次跑分一条记录，由 `remote/remote_selftest.sh` 与 `remote/submit_client.py`
在运行结束时自动生成，文件名即运行 ID（`YYYYMMDD-HHMMSS-<tag>.md`）。

自动填入：提交号（含是否有未提交改动）、模型、参数、各链路得分与分级分布、增益。
**需要手填**：「改动与假设」「结论」两节。没有结论的记录价值有限。

原始产物在 `../runs/<运行 ID>/`，不进版本库。

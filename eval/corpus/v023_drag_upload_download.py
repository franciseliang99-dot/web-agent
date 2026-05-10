"""V0.26.1 corpus: V0.23 drag/upload/download 能力轴 task (3 task).

upload task fixture 文件路径在 task 定义里写绝对路径 fake.txt; 但 fake.txt 不存在
runner 调 upload_file 时会落到 actuator → DOM walk → set_input_files raise. 为让 task
可跑, runner 在 chromium fixture launch 时创建 tmp upload 文件 (V0.26.3 cassette 中
固定路径). V0.26.1 task 定义 upload paths 用 placeholder, runner 渲染时替换.
"""

from __future__ import annotations

from eval.corpus._fixtures import (
    TOKEN_DOWNLOAD_FILENAME,
    TOKEN_DRAG_DROP_ACK,
    TOKEN_UPLOAD_FILENAME,
    URL_DOWNLOAD,
    URL_DRAG_DROP,
    URL_UPLOAD,
)
from eval.predicates import AllOf, Predicate, SubstringPredicate, TraceContainsAction, TraceObsContains
from eval.types import EvalTask

DRAG_DROP_TRELLO = EvalTask(
    task_id="v023-drag-src-to-dst",
    goal=(
        "页面有 SRC (绿色方块) 和 DROP HERE (蓝色方块) 两个元素. "
        "把 SRC 拖到 DROP HERE 后, DROP HERE 文本会变成一个 ack token. "
        "用 done(result=...) 返回这个 ack token"
    ),
    fixture_url=URL_DRAG_DROP,
    capability_axis="drag",
    expected_step_range=(3, 6),
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 真用 drag(from_mark_id=SRC, to_mark_id=DROP) 工具; V0.23.1 单段贝塞尔 mouse path",
    tags=("v023", "drag"),
)

UPLOAD_FILE_TO_INPUT = EvalTask(
    task_id="v023-upload-to-file-input",
    goal=(
        "页面有一个 file input. 用 upload 工具上传文件 /tmp/v026-corpus-fake.txt. "
        "上传后页面 ack 区会显示 'received: <filename>'. "
        "用 done(result=...) 返回 ack 区完整文本"
    ),
    fixture_url=URL_UPLOAD,
    capability_axis="upload",
    expected_step_range=(2, 5),
    max_steps=6,
    max_wallclock_s=45.0,
    description="LLM 真用 upload(mark_id, paths) 工具; V0.23.1 set_input_files 直接路径; runner 创建 tmp 文件",
    tags=("v023", "upload"),
)

DOWNLOAD_LINK_CLICK = EvalTask(
    task_id="v023-download-link-extract-filename",
    goal=(
        "页面有一个 'Download report' 链接, click 它触发文件下载. "
        "下载完成后下一步 obs 会出现 'downloaded: <filename>' 信息. "
        "用 done(result=...) 返回完整下载文件名"
    ),
    fixture_url=URL_DOWNLOAD,
    capability_axis="download",
    expected_step_range=(3, 6),
    max_steps=8,
    max_wallclock_s=45.0,
    description="LLM 真读 obs deque (V0.24.1 helper 注入); 验 trace obs 含 downloaded: 字样",
    tags=("v023", "download", "obs-reading"),
)

DRAG_UPLOAD_DOWNLOAD_PREDICATES: dict[str, Predicate] = {
    DRAG_DROP_TRELLO.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_DRAG_DROP_ACK),
        TraceContainsAction(action_type="drag", min_count=1),
    )),
    UPLOAD_FILE_TO_INPUT.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_UPLOAD_FILENAME),
        TraceContainsAction(action_type="upload", min_count=1),
    )),
    DOWNLOAD_LINK_CLICK.task_id: AllOf(predicates=(
        SubstringPredicate(substring=TOKEN_DOWNLOAD_FILENAME),
        TraceObsContains(substring="downloaded:"),
    )),
}

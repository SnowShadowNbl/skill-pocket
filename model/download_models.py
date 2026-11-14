"""把 FunASR 用到的模型下载到本目录（与容器内 /workspace/models 的目录结构一致）。

    pip install modelscope
    python model/download_models.py
"""

from pathlib import Path

from modelscope.hub.snapshot_download import snapshot_download

HERE = Path(__file__).resolve().parent
MODELS = [
    "damo/speech_fsmn_vad_zh-cn-16k-common-onnx",
    "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx",
    "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx",
    "damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx",
]

for model_id in MODELS:
    target = HERE / model_id
    print(f"下载 {model_id} → {target}")
    snapshot_download(model_id, local_dir=str(target))
print("完成")

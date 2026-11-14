# model/ · 语音转文字模型（FunASR）

SkillBase 的「按住说话」用阿里开源的 [FunASR](https://github.com/modelscope/FunASR)（MIT 许可）在自己服务器上识别，音频不出服务器。
本目录挂载到 FunASR 容器的 `/workspace/models`（见 `docker-compose.yml`）。

## 模型清单

| 目录（ModelScope ID） | 作用 | 主要文件 | 大小 |
|---|---|---|---|
| `damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx` | 流式识别：边说边出字 | `model_quant.onnx` + `decoder_quant.onnx` | 约 230MB |
| `damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx` | 离线识别：每句说完后修正 | `model_quant.onnx` | 约 230MB |
| `damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx` | 加标点 | `model_quant.onnx` | 约 270MB |
| `damo/speech_fsmn_vad_zh-cn-16k-common-onnx` | 断句（检测说话开始 / 结束） | `model_quant.onnx` | 约 1MB |

合计约 **730MB**，CPU 运行，内存约 0.9GB。均为 int8 量化的 ONNX 模型。

未使用：语言模型（`speech_ngram_lm_zh-cn-ai-wesp-fst`，约 1GB 内存，收益小）、ITN 数字规整模型（官方示例里的 `thuduyu/fst_itn_zh` 已从 ModelScope 下架）。

## 为什么模型文件不在 Git 里

单个模型文件 159～269MB，超过 Gitee 免费仓库单文件 100MB 的上限。所以 Git 里只放本说明、`hotwords.txt` 和下载脚本，模型文件本身在 `.gitignore` 里排除。

## 获取模型

两种方式任选：

1. **什么都不用做**：`docker compose up -d funasr` 首次启动时会自动从 ModelScope 下载到本目录。
2. **提前下载**（离线部署 / 换服务器时）：

   ```bash
   pip install modelscope
   python model/download_models.py
   ```

## 热词

`hotwords.txt` 每行一个词和权重（如 `SkillBase 20`），可提升专有名词的识别准确率；修改后 `docker compose restart funasr` 生效。

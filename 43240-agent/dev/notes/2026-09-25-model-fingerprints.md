# 模型权重指纹（2026-09-25 起）

记录每次测试所用权重的 sha256 与上游 commit，**用来确认两次跑分用的是同一份权重**。
没有这个记录，不同批次的分数就没有可比性。

## 怎么算的

在实例上对权重目录里的每个 `*.safetensors` 跑 `sha256sum`：

```bash
cd /workspace/models/<模型> && sha256sum *.safetensors
```

另外记录 HuggingFace 下载时写在 `.cache/huggingface/download/*.metadata` 里的
**上游 commit 号**——它把「仓库的哪个版本」钉死了，比文件哈希更早发现问题
（仓库更新但文件名不变时，commit 会变）。

## 2026-09-25 第二批（模板 `qwen`，vLLM 0.27.0）

| 模型 | HF 仓库 | 上游 commit | 权重文件 |
| --- | --- | --- | ---: |
| A1 | `QuantTrio/Qwen3.6-35B-A3B-AWQ` | `119886a1072372348f73ef0df2d801cdcc0f455b` | 9 |
| A2 | `QuantTrio/Qwen3.5-35B-A3B-AWQ` | `2f4fac011fc06e736782b0b59394577790da7d79` | 9 |
| A3′ | `QuantTrio/Qwen3.6-27B-AWQ`（A9 的替代，见下） | `9b507bdc9afafb87b7898700cc2a591aa6639461` | 8 |

### A1 `QuantTrio/Qwen3.6-35B-A3B-AWQ`

```
a03ac5037c331d2c6767cecc90ef571560b88a81a90e4834842e2e38a6a822b6  model-00001-of-00009.safetensors
9bf7aa9d3a7cd8a7becdb06067473fd08b363627233a062f556a190cdb28a3a8  model-00002-of-00009.safetensors
5915093625360f6b7ed5b248626fdf1ed4aaf0cd05301b5a310d2ea2fb254415  model-00003-of-00009.safetensors
887c7e148f244064ef82d4b99c51ee4760cfa8c0e1bd94673e826a656959cb91  model-00004-of-00009.safetensors
702b9c5c04fe9733708c5b0ec83a64271219a7acaa15b8d398debfd477e58e36  model-00005-of-00009.safetensors
69879d7d90c4e04d8360d0c0cf3c4a46d915bd2998b99b720806ea5837cf35a2  model-00006-of-00009.safetensors
1a7f71638dd9715e8f25a0dd3c7fd5dc77c64bbd615ef9bcd8a879e84f7fbd34  model-00007-of-00009.safetensors
cba9d0fb148b93b24702aef707cb4b8cdfa0e586ca418c5f4a0e75d557f239f0  model-00008-of-00009.safetensors
fcffbdad2da205c7f9ab7a0365aaaec09cb942de9b4b39346f00d62da90e1d9e  model-00009-of-00009.safetensors
```

### A2 `QuantTrio/Qwen3.5-35B-A3B-AWQ`

```
e561015778a08e9e2324c1e893cee6fb0b54da66d45ab084ffb87a0d8be7c563  model-00001-of-00009.safetensors
e6a41cb0e352ab1d87e919b5db1567f7a0aa230dd6e963602d9a7e5d3c23f7ef  model-00002-of-00009.safetensors
94268fa039cb9739529aae64fa342cedc056722fc744a5248c220c68dee8341a  model-00003-of-00009.safetensors
b6f2b384bb4d8bb650adc02d75973228170ce165668832754111655ffda991ee  model-00004-of-00009.safetensors
842512ac31fdc0f3166855aaea78c96d491421b5e3a91e4d06eac407f2956c32  model-00005-of-00009.safetensors
2ae6d4effcf9518e15fd35ade722c0183fb2bc73498e053664f1deefbd43c95a  model-00006-of-00009.safetensors
24e556456ab50bdbd9255baa1c5e988b7f9bf6bc4643f8bd6e5e0dee2f526e5b  model-00007-of-00009.safetensors
5e513dfbbbdf64efef65efc9f30796045fffe8cf6cd4ffc7559f580038cecaeb  model-00008-of-00009.safetensors
ad451187a3ed8f296575c13f726a72b1b592f598f7c1c9820b720fd31e1a1d9a  model-00009-of-00009.safetensors
```

### A3′ `QuantTrio/Qwen3.6-27B-AWQ`

```
edee5a3813fcb71b925de2cf8e1c7ae03c41e22e7623048aaed88c1736a6989d  model-00001-of-00008.safetensors
ee0b6bef0f142106ce4c80075cdcdbbe839c4d956eab8209db6fb0454718fe1f  model-00002-of-00008.safetensors
ba80a107abb0ad28d24a02f26cc8862b3fd12e7d9b5ba4c868e919b680fc61e2  model-00003-of-00008.safetensors
020906383c8bf2b21d182592480e07ec55850002c318129d36ca1a274a48709a  model-00004-of-00008.safetensors
de481de4b46a3c66b5db2e9396f848db9fb1cf1a5db493a4b45ac23fb3fefa60  model-00005-of-00008.safetensors
a8641fc034da7429c65315aeba9233b74becb8556187826971bf76a7e31a7026  model-00006-of-00008.safetensors
d8a124b71eb3ed61c27cbf34740bbda170c403668e5b5cec0965fb5f02ac94cd  model-00007-of-00008.safetensors
9bc04640721c03b0af13aeac48d87f1a8fbdd3f3d11cc4bbc5fe9547d1908fbe  model-00008-of-00008.safetensors
```

### 怎么复核

```bash
cd <本地权重目录> && sha256sum -c <把上面的清单存成文件>
```

## 缺口：第一批（2026-09-25 上午，模板 `gh-rtl-agent`）没有留指纹

A4、A5、A6、A7、Q1a、Q1b 那六次跑分用的权重（`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`、
`cyankiwi/Qwen3-Coder-30B-A3B-AWQ-4bit`、`Qwen/Qwen3-4B-Instruct-2507`、
`cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit`、`cyankiwi/Qwen3-4B-Instruct-2507-AWQ-8bit`、
`zhuyaoyu/CodeV-R1-RL-Qwen-7B`）**当时没有记 sha256**，实例也已经销毁。
仓库名写在各自的实验记录里，但**具体是哪个 revision 无法追溯**。

这条是流程漏洞：以后每批实验开始前先把权重哈希记进本文件，再开始跑分。
在 `dev/remote/joint_run.sh` 里加一步自动记录是待办。

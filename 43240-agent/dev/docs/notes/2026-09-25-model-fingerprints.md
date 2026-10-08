> **文档状态：归档笔记：结论、路径与命令反映当时实验或设计。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# 模型权重指纹（2026-09-25 起）

> **这份文档怎么用**：只追加、不改写。每批实验前用
> [`../remote/weights.sh`](../../tools/remote/weights.sh) 采集（`joint_run.sh` 会自动调用），
> 目的是回答「两次跑分用的是不是同一份权重」。
>
> - **两个标识都要记**：文件的 sha256（确认字节一致）与上游 commit（仓库更新但文件名不变时，
>   只有 commit 会变）。
> - **复核**：把某一节的代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。
> - **只记仓库名是不够的**——第一版文档就是因为只写了仓库名，实例销毁后无法追溯（见文末缺口一节）。

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
| `Qwen3.6-35B-A3B`（AWQ-4bit） | `QuantTrio/Qwen3.6-35B-A3B-AWQ` | `119886a1072372348f73ef0df2d801cdcc0f455b` | 9 |
| `Qwen3.5-35B-A3B`（AWQ-4bit） | `QuantTrio/Qwen3.5-35B-A3B-AWQ` | `2f4fac011fc06e736782b0b59394577790da7d79` | 9 |
| `Qwen3.6-27B`（AWQ-4bit，dense） | `QuantTrio/Qwen3.6-27B-AWQ`（`Qwen3.8-27B` 的替代，见下） | `9b507bdc9afafb87b7898700cc2a591aa6639461` | 8 |

### `QuantTrio/Qwen3.6-35B-A3B-AWQ`（Qwen3.6-35B-A3B，AWQ-4bit）

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

### `QuantTrio/Qwen3.5-35B-A3B-AWQ`（Qwen3.5-35B-A3B，AWQ-4bit）

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

### `QuantTrio/Qwen3.6-27B-AWQ`（Qwen3.6-27B，AWQ-4bit，dense）

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

`Qwen3-Coder-30B-A3B`（AWQ-4bit）、`Qwen3-30B-A3B-Instruct-2507`（AWQ-4bit）、`Qwen3-4B-Instruct-2507`（BF16）、`CodeV-R1-RL-Qwen-7B`（BF16）、`Qwen3-4B-Instruct-2507`（AWQ-4bit）、`Qwen3-4B-Instruct-2507`（AWQ-8bit） 那六次跑分用的权重（`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`、
`cyankiwi/Qwen3-Coder-30B-A3B-AWQ-4bit`、`Qwen/Qwen3-4B-Instruct-2507`、
`cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit`、`cyankiwi/Qwen3-4B-Instruct-2507-AWQ-8bit`、
`zhuyaoyu/CodeV-R1-RL-Qwen-7B`）**当时没有记 sha256**，实例也已经销毁。
仓库名写在各自的实验记录里，但**具体是哪个 revision 无法追溯**。

这条是流程漏洞：以后每批实验开始前先把权重哈希记进本文件，再开始跑分。
在 `dev/tools/remote/joint_run.sh` 里加一步自动记录是待办。

## 2026-09-28 夜间批次（B 层备选）

### GLM-4.7-Flash-AWQ-4bit

| 项 | 值 |
| --- | --- |
| HF 仓库 | `cyankiwi/GLM-4.7-Flash-AWQ-4bit` |
| 远端路径 | `/workspace/models/GLM-4.7-Flash-AWQ-4bit` |
| 上游 commit | 25624b53414e585bcf7dcb9584667c3106c6089b |
| 权重文件数 | 4 |

```
2d6793b5b0d81858925f3f5bd69da53d2e5f892c1a0182079097874555346e25  model-00001-of-00004.safetensors
6e7608d383596150c03f40ce3f6c6e463654578065052bfd40f8d52529549a60  model-00002-of-00004.safetensors
8401718639c81db88a209db5fc46fd80f3df038e4e33e41f904990c0b995cd1e  model-00003-of-00004.safetensors
49fa9892731203f6d251c5a6794a7975724ba7f59bd8099f2082b1a194d35508  model-00004-of-00004.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### Qwen2.5-Coder-7B-Instruct

| 项 | 值 |
| --- | --- |
| HF 仓库 | `Qwen/Qwen2.5-Coder-7B-Instruct` |
| 远端路径 | `/workspace/models/Qwen2.5-Coder-7B-Instruct` |
| 上游 commit | c03e6d358207e414f1eca0bb1891e29f1db0e242 |
| 权重文件数 | 4 |

```
0b6f069918b07c064cbba8ae4f00f529aa9bbf84b7cdfcb7fc2694a40f6aa8ef  model-00001-of-00004.safetensors
c3d46733e7aa054ea7b063fbccd0a5a08446e7bd1814bef26936c5aa1331da62  model-00002-of-00004.safetensors
9fe45dacee087385b3d2d6dd27a7413a8a56d95f145772facc148fa86fc73446  model-00003-of-00004.safetensors
5aa6e5cbe642377fd441fb4e60e83cca96b2bcd9820e245b9ea06d94653f17f2  model-00004-of-00004.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### Seed-OSS-36B-AWQ

| 项 | 值 |
| --- | --- |
| HF 仓库 | `QuantTrio/Seed-OSS-36B-Instruct-AWQ` |
| 远端路径 | `/workspace/models/Seed-OSS-36B-AWQ` |
| 上游 commit | e7a05d50620ee8bc1670fd76dffc7a724c2cb268 |
| 权重文件数 | 8 |

```
fcb92887d96a6e292db5409424b08df40a7f7eee1900f22e4446adcd2667f236  model-00001-of-00008.safetensors
d78765a1dec0ec6840e831228d540d26cc1803e9b5d5647d505cc94dda65834b  model-00002-of-00008.safetensors
f33cd2486137af21d0a3e639a84243047ab39ca20ad0076e403b18b7c2d43a2d  model-00003-of-00008.safetensors
ecd6b0af244c858d1b6825b9735ac932697a8e63bb8be44c7fa4477e8a6b9f1f  model-00004-of-00008.safetensors
0b328861cc4469b3da17aa9922e904a34638f61b2ebbd8ea63634539bfd80d40  model-00005-of-00008.safetensors
a176b18a344a12ad7a5aa2ee778ffa8342527a81270d92ad34ba1e4548d500af  model-00006-of-00008.safetensors
9e934df19e012819fccaec87b1af31d18fbc653638ef64bae94d5a9d1f3799f0  model-00007-of-00008.safetensors
4e97955ec7fdf519bd1e8819933b92f965765a25f5f8aa811b66765d26484bdd  model-00008-of-00008.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

## 2026-09-28 白天批次（B 层补测）

### gemma-4-12B-it

| 项 | 值 |
| --- | --- |
| HF 仓库 | `google/gemma-4-12B-it` |
| 远端路径 | `/workspace/models/gemma-4-12B-it` |
| 上游 commit | 707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7 |
| 权重文件数 | 1 |

```
5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d  model.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### GLM-4.7-Flash-AWQ-4bit

| 项 | 值 |
| --- | --- |
| HF 仓库 | `cyankiwi/GLM-4.7-Flash-AWQ-4bit` |
| 远端路径 | `/workspace/models/GLM-4.7-Flash-AWQ-4bit` |
| 上游 commit | 25624b53414e585bcf7dcb9584667c3106c6089b |
| 权重文件数 | 4 |

```
2d6793b5b0d81858925f3f5bd69da53d2e5f892c1a0182079097874555346e25  model-00001-of-00004.safetensors
6e7608d383596150c03f40ce3f6c6e463654578065052bfd40f8d52529549a60  model-00002-of-00004.safetensors
8401718639c81db88a209db5fc46fd80f3df038e4e33e41f904990c0b995cd1e  model-00003-of-00004.safetensors
49fa9892731203f6d251c5a6794a7975724ba7f59bd8099f2082b1a194d35508  model-00004-of-00004.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### Ministral-3-14B-AWQ-4bit

| 项 | 值 |
| --- | --- |
| HF 仓库 | `cyankiwi/Ministral-3-14B-Instruct-2512-AWQ-4bit` |
| 远端路径 | `/workspace/models/Ministral-3-14B-AWQ-4bit` |
| 上游 commit | d4401438aba6c4e523b929c1a8878d3fe8cc0bca |
| 权重文件数 | 4 |

```
ac75afd3829eab2f2c9e8184d3b6915c83a4cbe1c15559c7258ae501155ba0e0  consolidated.safetensors
b750275d75b03a5d75b5536cf2524329ca10b9a78f25a1f029492e35360e1151  model-00001-of-00003.safetensors
6f87f7f1d7521256c701186204a716e128338146bba86e3822fc0b4ab264b3c3  model-00002-of-00003.safetensors
e7a229d2867801bfbcb2dce1fcbed9fa110fef7eadf107c36d8021abb5f03060  model-00003-of-00003.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### Qwen2.5-Coder-7B-Instruct

| 项 | 值 |
| --- | --- |
| HF 仓库 | `Qwen/Qwen2.5-Coder-7B-Instruct` |
| 远端路径 | `/workspace/models/Qwen2.5-Coder-7B-Instruct` |
| 上游 commit | c03e6d358207e414f1eca0bb1891e29f1db0e242 |
| 权重文件数 | 4 |

```
0b6f069918b07c064cbba8ae4f00f529aa9bbf84b7cdfcb7fc2694a40f6aa8ef  model-00001-of-00004.safetensors
c3d46733e7aa054ea7b063fbccd0a5a08446e7bd1814bef26936c5aa1331da62  model-00002-of-00004.safetensors
9fe45dacee087385b3d2d6dd27a7413a8a56d95f145772facc148fa86fc73446  model-00003-of-00004.safetensors
5aa6e5cbe642377fd441fb4e60e83cca96b2bcd9820e245b9ea06d94653f17f2  model-00004-of-00004.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

## 2026-09-28 白天批次（续）

### Devstral-Small-2-AWQ-4bit

| 项 | 值 |
| --- | --- |
| HF 仓库 | `cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit` |
| 远端路径 | `/workspace/models/Devstral-Small-2-AWQ-4bit` |
| 上游 commit | 9218adca17d7153120cd5d583d24f94a893de529 |
| 权重文件数 | 5 |

```
bd6853e013022cffbe72071be2ba671b120f74736bfc41f1a1416af265f6c29a  consolidated.safetensors
b6b6f152486c962cf961888c1c0e19cfc58c9a88a5ac05d0f4b61f115a6ce888  model-00001-of-00004.safetensors
b6690b81a0073716e35257c2356569a9e34faf906d5d1f8741ccbc49e88dffbf  model-00002-of-00004.safetensors
2ee501a2dfb26d6f2fdd0e0a7056463fd9e8954e52ec995be17749ea02249caf  model-00003-of-00004.safetensors
c12fc2e792180ff2be82fdb95e82f4b48db28ae380a76a1475ddcf8224445c1c  model-00004-of-00004.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

### Qwen3-30B-2507-GPTQ4

| 项 | 值 |
| --- | --- |
| HF 仓库 | `btbtyler09/Qwen3-30B-A3B-Instruct-2507-gptq-4bit` |
| 远端路径 | `/workspace/models/Qwen3-30B-2507-GPTQ4` |
| 上游 commit | 906bfe3a98df46289591b374eeeddcbc35046a1e |
| 权重文件数 | 10 |

```
aad18b8a9ee96a87a08daf0aceb8953c5bd8056ed5d76191182e718513f6e06b  model-00001-of-00010.safetensors
6c1367bbcdd52c4135f1e6ed732a309d2f8d159630471ca0ea87f21aa3cf0213  model-00002-of-00010.safetensors
7fbe0246c927845aa0bafd7cce67511b0a52dace3a0eab5d59860decc1b5be26  model-00003-of-00010.safetensors
501bcd6d4bf3df98d864cf279e90b4d01e20b3409330d9ac566189528f55db00  model-00004-of-00010.safetensors
942d92d376233289cb19d12c7bcda77db48d00664f943590533b2e3c63b28885  model-00005-of-00010.safetensors
cafa94afc00bb6ccacf5312466030994dca0118c293637a0e2370dc28943def9  model-00006-of-00010.safetensors
c4430fb6a718ca732a385e18101acf63534758db0d7be8094192385581797e1c  model-00007-of-00010.safetensors
9a7611df46c6ef49df1e6e1f0933c451b418b954e118f7dda4470621f96f2c6c  model-00008-of-00010.safetensors
44bb07295e8cc3999ab50f1e7a0fb295371eed7bdba8caf5bdead5e314a64f96  model-00009-of-00010.safetensors
a6058203ece5247fa7cdd893ad61d91818ac78608d602a9e72a144234e6758d9  model-00010-of-00010.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。

## 2026-09-28 收尾补录（失败与新模型）

### Kimi-Linear-48B-AWQ-4bit

| 项 | 值 |
| --- | --- |
| HF 仓库 | `cyankiwi/Kimi-Linear-48B-A3B-Instruct-AWQ-4bit` |
| 远端路径 | `/workspace/models/Kimi-Linear-48B-AWQ-4bit` |
| 上游 commit | 5d029d1844aa64ec302e14466be7d0353c6e697f |
| 权重文件数 | 7 |

```
c8df10150106668d99e963459dde01a4b7220182e8cac4c89cbfaa357ac532bc  model-00001-of-00007.safetensors
6ce28ca2c2c4989bb8920d4161b2e510ecc851b76d707d5ac39813fe5642e396  model-00002-of-00007.safetensors
d4a54b30d007e4c41d053fa575a16c58222444ffc4f69933139c9774ef5243d8  model-00003-of-00007.safetensors
f35748c5c8bfcbfe970f34897004ce17ca5f9d7eeae192088e7c96492f7d19c9  model-00004-of-00007.safetensors
570347383d8f33792bf1342328c0b457dbf561921968c54761dc98a7d1989cca  model-00005-of-00007.safetensors
9424715f117eb3b3a087e309c1b328ba0781f6fff35c30bd6e838c3327e4b41d  model-00006-of-00007.safetensors
f48b38d4babdd612596f419fbf64f1551d94d47098a008637720dc3c276b9d5e  model-00007-of-00007.safetensors
```

复核：把上面代码块存成文件，在权重目录里跑 `sha256sum -c <文件>`。


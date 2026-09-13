# NDAX 文件名与光照标签核对

核对日期：2026-09-12。范围为用户提供的 15 个 NDAX，未修改或重命名任何原文件。

## 结论

15 个文件按设备 45、单元、通道 1、TestID、开始时间和测量记录比对，归属 **6 组测试记录**，并非 15 组独立实验。
确认存在外部文件名与文件内自定义名称的冲突，以及同一实验不同导出版本之间的冲突。
“内部名称”来自 TestInfo.xml → config → Backup 的 Value JSON → CustomFileName，LastBackupFilePath 也保存了相同命名。
这两个字段属于人工命名/备份信息，不是光强传感器测量，不能单独证明实际照射强度。

| 单元 / TestID | 开始时间 | 文件编号 | 光照/材料标签核对 |
|---|---|---|---|
| 11 / 2818575312 | 2026-07-28 14:40:17 | #5、#6、#7 | 外名全为 16cm0.2sun，内部全为 8cm1sun |
| 2 / 2818575312 | 2026-07-28 14:40:35 | #9、#13、#14 | 外名分别为首圈 dark + 第二圈 8cm1sun、16cm0.2sun；内部全为 8cm1sun |
| 11 / 2818575313 | 2026-07-31 14:09:12 | #1、#8 | 外名分别为 12cm0.5sun、DARK；内部均为 12cm0.5sun |
| 2 / 2818575313 | 2026-07-31 14:08:52 | #10、#15 | 外名分别为 12cm0.5sun、DARK；内部均为 12cm0.5sun |
| 11 / 2818575314 | 2026-08-06 14:39:49 | #2、#4 | 内外均为 sno2zmo、12cm0.5sun，未发现命名冲突 |
| 2 / 2818575314 | 2026-08-06 14:39:35 | #3、#11、#12 | 光照都为 12cm0.5sun，但材料名 sno2zmo / zmo 冲突；内部均为 sno2zmo |

## 测量记录证据

逐条比较每条 87 字节有效测量记录，不只是比较曲线外观。以下短版本的全部记录均与长版本对应前缀字节一致：

| 文件配对 | 共同记录全部相同 | 较长文件新增记录 |
|---|---:|---|
| #1（0.5 sun） ↔ #8（DARK） | 26,036 条 | #8 多 3 条，约 60 s |
| #10（0.5 sun） ↔ #15（DARK） | 26,030 条 | #15 多 4 条，约 80 s |
| #9（dark + 1 sun） ↔ #13、#14（0.2 sun） | 12,862 条 | #9 多 8 条，约 160 s |
| #3（sno2zmo） ↔ #11、#12（zmo） | 4,011 条 | #3 多 4 条，约 80 s |
| #5 ↔ #6、#7 | 8,675 条 | #6、#7 多 11 条，约 220 s |
| #2 ↔ #4 | 4,007 条 | #2 多 6 条，约 120 s |

#6 与 #7、#11 与 #12、#13 与 #14 的 data.ndc 完全一致。
所以 DARK 和光照标签冲突的这些副本不能分别用于暗态/光照对照，也不能把重复导出计为重复实验。
如果原实验确实在同一测试中切换照明，应该按实验日志中的时间或循环区间分段，而不是把整份相同数据分别冠以不同条件。

## 哪一种光强才正确？

- 五个外名带 16cm0.2sun 的文件（#5、#6、#7、#13、#14）内部名称均是 8cm1sun，是首要核对对象。
- 两个 DARK 文件（#8、#15）内部名称均是 12cm0.5sun，并与同名光照版本共享整段测量数据。
- #9 的“首圈暗态、第二圈 1 sun”是外部名称新增的分段说明；内部名称只写 8cm1sun，不能凭它确认开关灯时刻。
- 所有文件的 AuxCount 都是 0，也没有辅助通道文件；未发现可独立核实 sun 数值的光强测量数据。
- 因此可以确认命名不一致，但不能排除后来改名是在纠正原始备注。不要仅凭内部名称自动重命名。
- 建议按上表的通道、开始日期时间与实验日志、光强计/模拟太阳光校准记录核对。当前把冲突组光照条件标为“待确认”，每组保留记录最完整的一个版本用于数据浏览，保留所有原附件用于溯源。

## 全部文件索引

### #1 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-11-1-2818575313.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-11-1-2818575313.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575313。
- 开始：2026-07-31 14:09:12；有效记录：26,036 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：与 #8 为同一实验；外名分别为 0.5 sun / DARK。
- 测量记录 SHA-256：`086c7604c82331c45a7c8a8361a2ebea8ebf614e2e3ff2febc7e4d310c468619`。

### #2 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-11-1-2818575314.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-11-1-2818575314.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575314。
- 开始：2026-08-06 14:39:49；有效记录：4,013 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：与 #4 同一实验，较 #4 多 6 条。
- 测量记录 SHA-256：`90b45eae6bd3d99bca4f778b91f77a520ab733f5cea648be075feb42b328dfa6`。

### #3 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575314.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575314.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575314。
- 开始：2026-08-06 14:39:35；有效记录：4,015 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：与 #11、#12 同一实验，但材料名 sno2zmo / zmo 冲突。
- 测量记录 SHA-256：`f23fc147ae0f79f5d780937d9e74c85165d818f9d5a71be29d7445bfb05ca5f3`。

### #4 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun_127.0.0.1-BTS82-45-11-1-2818575314.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun_127.0.0.1-BTS82-45-11-1-2818575314.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575314。
- 开始：2026-08-06 14:39:49；有效记录：4,007 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：与 #2 同一实验的较早导出。
- 测量记录 SHA-256：`f9f7169f52b6368fb343b58e0268ca199368b83735344907a4730437f68c4558`。

### #5 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun-240045-11-1-2818575312.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun-240045-11-1-2818575312.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:17；有效记录：8,675 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名 0.2 sun，内部 1 sun；与 #6、#7 同一实验。
- 测量记录 SHA-256：`e88fecb9e990733b0697bc314de563281a44e96a78d8fbf226569fd887516e65`。

### #6 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun_127.0.0.1-BTS82-45-11-1-2818575312 (2).ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun_127.0.0.1-BTS82-45-11-1-2818575312 (2).ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:17；有效记录：8,686 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名 0.2 sun，内部 1 sun；与 #7 测量完全相同。
- 测量记录 SHA-256：`1bcdae95007783a0aea7037973153314098a9aaa000b8518d8b8a62c7a44a250`。

### #7 sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun_127.0.0.1-BTS82-45-11-1-2818575312.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun_127.0.0.1-BTS82-45-11-1-2818575312.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:17；有效记录：8,686 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名 0.2 sun，内部 1 sun。
- 测量记录 SHA-256：`1bcdae95007783a0aea7037973153314098a9aaa000b8518d8b8a62c7a44a250`。

### #8 sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313.ndax>)

- 设备/单元/通道：45 / 11 / 1；TestID：2818575313。
- 开始：2026-07-31 14:09:12；有效记录：26,039 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：外名 DARK，内部 0.5 sun；比 #1 多 3 条。
- 测量记录 SHA-256：`b38511319a6f78ea0655c90b0753262b8cd94ff4ed50ab42072ba63d36007eeb`。

### #9 zmo, 0.05ma,cm2dcg. 0.18cm2, 1st dark +2nd light 8cm1sun_127.0.0.1-BTS82-45-2-1-2818575312.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, 1st dark +2nd light 8cm1sun_127.0.0.1-BTS82-45-2-1-2818575312.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:35；有效记录：12,870 条。
- 内部 CustomFileName：`zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名首圈暗态+第二圈1 sun；与 #13、#14 是同一实验。
- 测量记录 SHA-256：`6427419c8e3f35ee5c6fd115a281ace19898e58c33abe961d0b1ada255dea4ed`。

### #10 zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575313.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575313.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575313。
- 开始：2026-07-31 14:08:52；有效记录：26,030 条。
- 内部 CustomFileName：`zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：与 #15 同一实验；外名分别为 0.5 sun / DARK。
- 测量记录 SHA-256：`225f07932fcfba97b4637a6f6ae370f55035f93869f24bd0e4cd81eda439d1c2`。

### #11 zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575314.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun-240045-2-1-2818575314.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575314。
- 开始：2026-08-06 14:39:35；有效记录：4,011 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：外名 zmo，内部 sno2zmo；与 #12 测量完全相同。
- 测量记录 SHA-256：`45733d937aee00bca8864c9162c745c5447007c8d81c9787a75e21df41b511cf`。

### #12 zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun_127.0.0.1-BTS82-45-2-1-2818575314.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun_127.0.0.1-BTS82-45-2-1-2818575314.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575314。
- 开始：2026-08-06 14:39:35；有效记录：4,011 条。
- 内部 CustomFileName：`sno2zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：外名 zmo，内部 sno2zmo。
- 测量记录 SHA-256：`45733d937aee00bca8864c9162c745c5447007c8d81c9787a75e21df41b511cf`。

### #13 zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun-240045-2-1-2818575312.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, light 16cm0.2sun-240045-2-1-2818575312.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:35；有效记录：12,862 条。
- 内部 CustomFileName：`zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名 0.2 sun，内部 1 sun；比 #9 少 8 条。
- 测量记录 SHA-256：`2b8479401d97bb80947448ec9a82fdf1f4b80b4c07ac52f15ab98457b053eb7d`。

### #14 zmo, 0.05ma,cm2dcg. 0.18cm2, light16cm0.2sun_127.0.0.1-BTS82-45-2-1-2818575312.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. 0.18cm2, light16cm0.2sun_127.0.0.1-BTS82-45-2-1-2818575312.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575312。
- 开始：2026-07-28 14:40:35；有效记录：12,862 条。
- 内部 CustomFileName：`zmo, 0.05ma,cm2dcg. 0.18cm2, light 8cm1sun`。
- 核对结果：外名 0.2 sun，内部 1 sun；与 #13 测量完全相同。
- 测量记录 SHA-256：`2b8479401d97bb80947448ec9a82fdf1f4b80b4c07ac52f15ab98457b053eb7d`。

### #15 zmo, 0.05ma,cm2dcg. DARK_127.0.0.1-BTS82-45-2-1-2818575313.ndax

[打开原文件](<C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/zmo, 0.05ma,cm2dcg. DARK_127.0.0.1-BTS82-45-2-1-2818575313.ndax>)

- 设备/单元/通道：45 / 2 / 1；TestID：2818575313。
- 开始：2026-07-31 14:08:52；有效记录：26,034 条。
- 内部 CustomFileName：`zmo, 0.05ma,cm2dcg. 0.18cm2, light 12cm0.5sun`。
- 核对结果：外名 DARK，内部 0.5 sun；比 #10 多 4 条。
- 测量记录 SHA-256：`c02e288cf4ca7ef85eb60d136ae67ace48ea890f4154bba8360e397101f01fa1`。



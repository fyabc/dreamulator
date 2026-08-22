# 神话层累与系统发生学（Myth Stratigraphy & Phylogenetics）

本文汇总"神话/传说作为可追溯的文化遗产"这一研究方向的核心方法与结论：
民间故事和神话母题如何随人群迁徙而垂直传承、如何在演变中层累变形、
以及如何用系统发生比较法（PCM）重建它们的谱系。这是文明层"上古文明
记忆"设计的知识底座。

> 调研来源：2026-08-15 interlude 调研（完整版含全部文献见
> `../../../private/research/2026-08-15-pcm-cultural-phylogenetics.md` 与
> `2026-08-15-myth-case-studies.md`）。
>
> **现实可信度标注规范**：本文所有结论按三档标注——【共识】、
> 【弱校准】（方向合理但年代/细节依赖模型外推）、【大胆假说】
> （远未被接受）。dreamulator 引擎与世界设计消费这些知识时，
> 必须区分"可直接作为硬约束的共识"与"只能作为可能性选项的假说"。

---

## 一、方法：系统发生比较法（PCM）简史

- **Felsenstein (1985, *Am. Nat.*)**【共识】：跨物种/跨文化比较时样本
  因共同祖先而不独立（"伪重复"），必须用系统发生校正。奠基工具：
  独立对比法（PIC）。
- **工具箱**【共识】：PGLS（Grafen 1989）、系统发生信号（Pagel's λ 1999、
  Blomberg's K 2003；注意 K/λ 对行为与文化性状普遍偏弱）、祖先状态
  重建（简约/似然/贝叶斯随机映射）、BEAST 分化时间估计、NeighborNet
  网络（检测垂直继承与横向借用的冲突信号）。
- **文化转向：Mace & Pagel (1994, *Current Anthropology*)**【共识框架】：
  用**语言谱系树**作为文化比较的脚手架（语言垂直传承清晰，常与人群
  历史耦合），处理跨文化统计的 Galton's problem。
- **民间故事实证**：
  - Tehrani (2013, *PLOS ONE*)【共识：方法示范】：小红帽 58 个异文 ×
    72 个叙事特征建树 + 网络分析——ATU 333 与 123 是独立故事；
    东亚"虎姑婆"被判定为**两条西方谱系的水平杂交**而非古老祖型。
  - Graça da Silva & Tehrani (2016, *R. Soc. Open Sci.*)【较强共识，
    数字可议】：275 个故事类型 × 50 个印欧人群；《铁匠与魔鬼》
    （ATU 330）在原始印欧语节点稳健存在（后验概率 87%）——
    "6000 岁"应读作**与语言树节点绑定的点估计**，非独立测年。
- **深度时间重建**：
  - d'Huy 系列（Cosmic Hunt >1.5 万年、Polyphemus、龙、洪水）
    【弱校准→大胆假说：随时间深度递减】；
  - Witzel (2012) Laurasian/Pan-Gaean 地层框架【大胆假说：非形式化
    PCM，年代与证据链均受质疑】；
  - Delbrassine et al. (2025, bioRxiv 预印本)：母题分布与古 DNA
    出非洲信号平行【进行中，未评审】。

## 二、三大争议（设计时必须知道）

1. **水平传播 vs 树模型**【借用不致命，但有条件】：模拟研究
   （Greenhill et al. 2009; Currie et al. 2010）表明现实水平的借用
   通常不摧毁系统发生信号——除非性状被"捆绑式"借用。树 + 网络
   并用是标准做法。
2. **年代依赖语言树**【全领域最硬的技术软肋】：故事年代 = 语言树
   节点年代 × 存续概率。印欧树本身有安纳托利亚说 vs 草原说之争
   （古 DNA 近年偏向草原）；深时重建（万年以上）基本没有独立校准点。
3. **编码主观性与民俗学批评**：特征切分由研究者手工完成；
   Zipes 主张童话多源发生（polygenetic）；Liberman 主张母题级
   （Thompson 索引）而非故事类型级编码；ATU 类型本身是以欧洲
   为中心的学者建构。

**口头传统的实证年代上限**：Nunn & Reid (2016, *Australian Geographer*)
【共识】——澳洲原住民口传故事准确保存 ≥7000 年的海岸淹没事件。
再往上的年代主张均属模型外推。

## 三、层累机制库（真实案例 → 可设计的规则类型）

神话在传承中变形的机制，可直接写成文明层的"神话变异规则"：

| 机制 | 定义 | 真实案例 |
|---|---|---|
| **历史化/去神化** | 神 → 传说帝王 → 凡人 | 中国古史"层累造成"（顾颉刚命题）；希腊神话的欧赫迈罗斯化 |
| **Etiology 反转** | 历法/星官等实用知识失落后，被重新解释为叙事 | 织女本为授时星官，叙事化是知识失落的产物（刘宗迪）；"十日"很可能是十干纪"旬"制的神话化（刘宗迪、钟敬文） |
| **宗教叠写** | 新宗教吸收旧神职能与形象 | 猕猴祖神话佛教化：观音化身猕猴 + 罗刹女（7 世纪后，藏地） |
| **碎片杂交** | 两条谱系的故事模块重组成新故事 | Tehrani 判定东亚"虎姑婆"为小红帽 × 狼和七只小山羊的杂交 |
| **天文拟人化** | 天体位置关系 → 追逐/婚配叙事 | 猎户座追逐昴星团（希腊、澳洲原住民同构） |
| **数字张力叙事** | 观测与传说的数字差（七 vs 六）催生解释性故事 | "丢失的普勒阿得斯"（Merope/Electra 隐没）；日本"六连星" |

## 四、三组案例速查（含可信度）

### 4.1 昴星团"七姐妹"

- 全球分布：希腊 Pleiades、澳洲原住民七姐妹歌路、日本すばる（六星）、
  中国昴宿（历法星官）与民间"七姐妹星/七姑星"、菲律宾七位天女、
  印度 Krittika。共性：一组女性 + 猎户座追逐者 + 缺失的一颗星。
- Norris & Norris (2021)：结合 Gaia 恒星自行（Pleione 约 10 万年前
  才与 Atlas 视觉上分离），提出故事可能早于走出非洲【大胆假说】。
- d'Huy & Berezkin (2017)：母题建树显示弱水平传播信号【弱校准】。
- **中国支系结论**：七夕/牛郎织女依托织女星（Vega）与牵牛星，与
  昴星团是不同恒星指涉；主流判断为独立发展 + 观星认知趋同，
  与全球七姐妹谱系**无同源证据**【较稳的判断】。

### 4.2 环太平洋射日/多日

- 分布：后羿射十日（汉）、那乃三日神话（通古斯）、朝鲜二日二月、
  台湾原住民二日神话（布农祭月历）、苗瑶壮侗射日史诗、美洲
  "小动物射热日"（结构不同：射的是唯一过热之日）。
- Berezkin (2023) 与 Riftin (2023)【较稳】：该母题为**东亚起源 +
  沿南亚语系/南岛语系/通古斯迁徙多次扩散**；"白令时代共同祖型"
  版本证据变弱（美洲对应物结构不同且稀少）。
- 竞争解释：幻日（大气光学）、十干旬制历法说、独立发明。
  在中国语境中历法说有独立价值【较高共识（中国天文史学界）】。

### 4.3 "伪人"/野人与古人类假说

- 全球野人传说结构相似（毛、双足、林居、似人非人）【共识】。
- "传说保存与古人类实际相遇的记忆"【低：主流拒绝】：
  最严肃版本是 Forth（ebu gogo ↔ *Homo floresiensis*，有 1984 年
  民族志一手材料，但被主流古人类学拒绝，Peter Brown 书评指出
  解剖细节不符与年代间隔问题）；Shackley/Porshnev 的尼安德特残存
  说已被弃置；巨猿说被 2024 年灭绝年代研究（约 30 万年前已灭绝、
  从未到达美洲）与 Sykes et al. (2014) 毛发 DNA 分析否定。
- **无任何系统发生研究证明野人母题为走出非洲共同遗产**【现状】。
- 更被接受的解释：灵长类误认、化石的地神话学解释（Adrienne Mayor：
  独眼巨人 ↔ 矮象头骨）、巫术的社会控制功能（Kluckhohn 论
  skinwalker）、changeling = 对发育障碍的民间解释（Eberly 1988）。
- **设计含义**：这类假说在世界构建中只能作为"可能性选项"
  （如分支宇宙法则），不能作为默认事实。

## 五、物理锚定：神话与引擎 ground truth 的接口

dreamulator 相对现实民俗学的独特优势：引擎拥有可定年的物理事件
（日食、海侵海退、超新星、气候突变）。设计上古记忆时：

1. 让祖型神话**引用**引擎事件（事件 UUID → 母题 attestations）；
2. 世界内学者用这些锚点给神话断代（对应 Nunn & Reid 式的
   地质锚点在现实中的作用）；
3. 锚点之外允许世界内学界争论——这正是"研究视角"的内容来源。

## 六、汉藏语系猴祖神话（视频延伸，本土先驱）

王小盾 (1997,《中国社会科学》)：45 例猴祖神话的发生学分类 +
"猴"名同源词构拟——\*mlɔk（上古"猱/夔"、方言"马骝"）、\*mloŋ
（猩/獽）、\*sliŋ（十二辰之"申"）；嬗变路线"由藏缅而华夏、而壮侗"；
明确提出"种系发生树的描写方法可以成为神话研究的基本方法"。
藏族猕猴变人（佛教化叠写）、羌族猴婚神话为其素材。
**孙悟空前身与藏缅猴祖神话的关系尚无正式定量研究——学术空白，
创作自由度高**【现状标注】。

## 七、与 dreamulator 的对接方向

- 数据模型设计稿：`../../design/myth-strata.md`（母题 UUID 实体 +
  树/网络 + 层累规则 + 认知姿态）。
- 与语言谱系的联动：母题随语言树传播是 Mace & Pagel 范式的直接
  应用——母题分布可与 `Culture.language_id` 的语言谱系对齐，
  见 `../../design/language-phylogeny.md`。
- 叙述的认知姿态参数（omniscient vs in-world scholar）：
  narrate 子系统的扩展方向。

## 参考资料

- Felsenstein, J. (1985). Phylogenies and the Comparative Method. *Am. Nat.* 125: 1–15.
- Mace, R. & Pagel, M. (1994). The comparative method in anthropology. *Curr. Anthropol.* 35: 549–571.
- Tehrani, J. J. (2013). The Phylogeny of Little Red Riding Hood. *PLOS ONE* 8: e78871.
- Graça da Silva, S. & Tehrani, J. J. (2016). Comparative phylogenetic analyses uncover the ancient roots of Indo-European folktales. *R. Soc. Open Sci.* 3: 150645.
- d'Huy, J. (2013). A Cosmic Hunt in the Berber sky. *Les Cahiers de l'AARS* 15: 93–106；(2013) Polyphemus. *Nouvelle Mythologie Comparée* 1: 3–18；(2020) *Cosmogonies*. La Découverte；(2025) *Dragon*. Armand Colin.
- Witzel, E. J. M. (2012). *The Origins of the World's Mythologies*. OUP.
- Delbrassine, H. et al. (2025). Worldwide patterns in mythology echo the human expansion out of Africa. *bioRxiv* doi:10.1101/2025.01.24.634692.
- Norris, R. P. & Norris, B. R. M. (2021). Why are there Seven Sisters? *Advancing Cultural Astronomy*, 223–235.
- d'Huy, J. & Berezkin, Y. (2017). How Did the First Humans Perceive the Starry Night? *RMN Newsletter* 12–13: 100–122.
- Nunn, P. D. & Reid, N. J. (2016). Aboriginal Memories of Inundation of the Australian Coast. *Australian Geographer* 47: 11–25.
- Berezkin, Y. (2023). The Solar Mythology of Eastern Asia. *Folklore: Structure, Typology, Semiotics* 6(4): 51–79；Riftin, B. L. (2023). 同刊 6(4): 14–50.
- Forth, G. (2022). *Between Ape and Human*. Pegasus；Brown, P. 书评（peterbrown-palaeoanthropology.net）。
- Sykes, B. C. et al. (2014). Genetic analysis of hair samples attributed to yeti, bigfoot... *Proc. R. Soc. B* 281: 20140161.
- Eberly, S. S. (1988). Fairies and the Folklore of Disability. *Folklore* 99(1): 58–77.
- Kluckhohn, C. (1944). *Navajo Witchcraft*. Peabody Museum Papers 29.
- 王小盾 (1997). 汉藏语猴祖神话的谱系.《中国社会科学》第 6 期.
- 刘宗迪：《天文学史上的"织女"与"牛郎"》《太阳神话、〈山海经〉与上古历法》（中国民俗学网）.
- Greenhill, Currie & Gray (2009). Does horizontal transmission invalidate cultural phylogenies? *Proc. R. Soc. B* 276: 2299–2306.
- Zipes, J. (2006). *Why Fairy Tales Stick*. Routledge；Liberman (2016) Language Log "Folktale phylogeny".

# 常见音变类型库（Sound Change Library）

本文按机制分类整理跨语言常见的音变类型，每类附现实例与在 SCA 规则
语法中的写法示意。用途有二：设计架空语系音变清单时的"菜单"；未来
为 SCA 引擎提供默认音变预设库（preset library）的底稿。

> 调研来源：2026-08-15 interlude 调研。主要依据：Zompist《Ask Zompist: Common sound changes》(2019)、
> Campbell (2021) *Historical Linguistics*、`docs/knowledge/sca.md` 已有的音变理论节。

---

## 一、弱化与脱落（Lenition / Elision）

最常见的音变方向——发音省力驱动，通常发生在弱位置（元音间、非重读、词尾）。

| 音变 | 示例 | SCA 示意 |
|---|---|---|
| 元音间浊化 | 拉丁 -t- > 西班牙 -d-（vita > vida） | `t > d / V _ V` |
| 元音间擦化 | 拉丁 -p t k- > 西班 -β ð ɣ-；日语 k > ɣ 类弱化 | `p > B / V _ V` |
| 弱化链（典型序列） | p > b > β > ∅；t > d > ð > ∅；k > g > ɣ > ∅ | 多代模拟逐段应用 |
| 词尾辅音脱落 | 古法语词尾辅音大规模脱落；中古汉语韵尾脱落（触发声调化，见 tonogenesis.md） | `C > ∅ / _ #` |
| 非重读元音弱化/脱落（syncope） | 英语历史 *hlāford > lord；俄语非重读元音弱化 | `V > ∅ / 非重读位置` |
| 词首辅音脱落（aphaeresis） | 英语 *kn- > n-（knife 的 k 脱落） | `k > ∅ / # _ n` |

## 二、强化（Fortition）

弱化的反方向，较少见，常发生在词首等强位置。

| 音变 | 示例 |
|---|---|
| 擦音塞化 | 日耳曼语 \*b d g > p t k 的部分方言演变；部分班图语 |
| 送气化 | 挤喉音退化为送气音（本包 Vha'Klik 示例：`p' > p^h`） |

## 三、同化（Assimilation）

相邻音变得相似。分顺同化（受前面音影响）与逆同化（受后面音影响，更常见）。

| 音变 | 示例 | SCA 示意 |
|---|---|---|
| 鼻音部位同化 | 拉丁 in-possible > impossible；in-regular > irregular | `n > m / _ p` 等 |
| 元音和谐 | 土耳其语 -lar/-ler；本包 harmony.py 已实现 | 词级特征传播 |
| 腭化（palatalization） | k > tʃ / _i（拉丁 centum > 法语 cent；汉语见组腭化） | `k > tS / _ i` |
| 唇化（labialization） | k > kʷ / _u 类 | 特征规则 |
| 鼻化扩散 | 元音在鼻辅音旁鼻化（法语元音鼻化的前身） | `V > V~ / _ N` |

## 四、异化（Dissimilation）

相同/相似音为避免重复而变得不同。

| 音变 | 示例 |
|---|---|
| 拉丁 -l-…-l- > -r-…-l- | peregrinus 类；英语 marble < 古法语 marbre 的异化 |
| 草书/连读异化 | 两个相邻送气音失去一个送气（Grassmann 定律，希腊语/梵语） |

## 五、换位（Metathesis）

音段顺序互换。

| 示例 | 说明 |
|---|---|
| 英语 bird < 古英语 bridd；third < þridda | r/元音换位是高频类型 |
| 西班牙语 palabra < 拉丁 parabola | 流音换位 |

SCA 支持性：换位需要多段规则语义（当前 sca.py 以单段替换为主，
换位可作为 Phase 2+ 扩展）。

## 六、增音（Epenthesis / Insertion）

| 音变 | 示例 | SCA 示意 |
|---|---|---|
| 辅音丛破开（anaptyxis） | 借词适配时插入元音（日语借词 burst > バースト） | `∅ > V / C _ C`（受限丛） |
| 词首增音（prothesis） | 拉丁 schola > 古法语 escole > école；希腊语词首补元音（喉音消失的痕迹！） | `∅ > V / # _ sC` |
| 词尾增音（paragoge） | 部分语言借词词尾补元音 | `∅ > V / C _ #` |

**注意**：词首补元音正是喉音消失留下的典型"疤痕"之一
（\*h₂ster- > 希腊语 astḗr）——幽灵音段设计的常用工具，
见 `comparative-method.md` 第四节。

## 七、链式推移（Chain Shift）

一个音位的变化挤占相邻音位的空间，引发连锁腾挪。

| 类型 | 机制 | 经典案例 |
|---|---|---|
| 推链（push chain） | 低位音变逼近高位音，高位音被迫移动 | 格林定律的塞音整体移位（部分解读） |
| 拉链（pull/drag chain） | 高位音先空出位置，低位音被"吸入" | 英语元音大推移（Great Vowel Shift） |

本包 sca.py 已支持链式音变的代际模拟（README 示例与 test_sca.py）。

## 八、补偿性延长（Compensatory Lengthening）

音段脱落时，其"时长份额"转移给相邻元音。

| 示例 | 说明 |
|---|---|
| 喉音延长：\*eHC > ēC | 喉音理论三大效应之一（comparative-method.md §4.2） |
| 鼻音脱落 + 元音延长 | 法语元音鼻化链的后续阶段 |

## 九、类推与例外（非音变的"音变"）

新语法学派框架下，表面例外主要来自两个非语音机制，**设计架空语系时
必须显式建模，否则女儿语会"过于规则"而失真**：

1. **类推平整（analogical leveling）**：说话人把不规则形式改造成规则形式。
   例：英语 help 的过去式本为 holp（元音交替），被类推改造为 helped。
   方向通常是"规则形式吃掉不规则形式"，但高频词更抗类推
   （be/was、go/went 等高频异干互补得以幸存）。
2. **借词绕过（borrowing bypass）**：借词不经过（或晚经过）本语音变。
   例：拉丁语词首 /k/ 在法语中颚化为 /s/（cent），但借自拉丁语的
   学术词保留 /k/ 类读法。借词的音韵轮廓因此可以暗示借入年代——
   这是"语言史分层可读"的实现机制。

## 十、音变排序语义（feeding / bleeding）

音变按时间序串行应用，后规则与前规则的交互有两种：

- **feeding（喂给）**：前规则制造的环境被后规则利用
  （如先 `k > tʃ / _ i`，再有 `tʃ > ʃ` 作用于新产生的 tʃ）；
- **bleeding（遮蔽）**：前规则消除了后规则的适用环境
  （如先丢失词尾元音，使"元音间弱化"失去环境）。

设计音变清单时应有意识地安排 feeding/bleeding——它是同一套规则
在不同女儿语中产生不同结果的主要手段（同一祖语 + 同一组规则
但**顺序不同** → 不同的女儿语）。

## 十一、功能负荷检查（functional load）

无约束的音变会导致同音词爆炸、音位系统崩塌。设计实践：

- 关注高功能负荷的对立（区分大量词对的音位对立）——让它们晚变或不变；
- 生成后统计同音词数量，超过阈值时告警（可作为引擎的一致性检查项）。

## 参考资料

- Zompist. *Ask Zompist: Common sound changes* (2019). https://zompist.wordpress.com/2019/01/26/ask-zompist-common-sound-changes/
- Campbell, L. (2021). *Historical Linguistics: An Introduction*, 4th ed. Edinburgh University Press.
- Hock, H. H. & Joseph, B. D. (2009). *Language History, Language Change, and Language Relationship*, 2nd ed. Mouton de Gruyter.
- 本包内参考：`docs/knowledge/sca.md`（音变理论与规则语法）、`docs/sca-guide.md`（SCA 引擎 API）。

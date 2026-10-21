from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import (
    Book, CanonicalKnowledgePoint, CanonicalRelation, CanonicalTopic, CourseKnowledgeBinding,
    CourseOutlineBinding, CourseRequirement, CourseTemplateBinding, CurriculumTemplate, Enrollment,
    KnowledgePoint, KnowledgeRelation, OutlineDocument, OutlineEntry, StudentState, Topic,
)
from .extraction import normalize_name


TEMPLATE_CODE = "DATA-STRUCTURES-OPENDSA-CS2023"

# A deliberately curated teaching skeleton: OpenDSA supplies module/algorithm coverage,
# CS2023 supplies the higher-education scope, and common Chinese textbook terminology
# supplies aliases. Interactive AVs and exercises remain external resources for now.
TOPICS = [
    ("DS.01", None, "绪论与算法分析", "绪论,基本概念,算法分析", 1),
    ("DS.01.01", "DS.01", "数据结构基本概念", "逻辑结构,存储结构,抽象数据类型", 2),
    ("DS.01.02", "DS.01", "算法与复杂度", "算法分析,时间复杂度,空间复杂度", 2),
    ("DS.02", None, "线性表", "线性结构,表", 1),
    ("DS.02.01", "DS.02", "顺序表", "顺序存储,数组实现", 2),
    ("DS.02.02", "DS.02", "链表", "单链表,双链表,循环链表", 2),
    ("DS.03", None, "栈和队列", "栈与队列", 1),
    ("DS.03.01", "DS.03", "栈", "顺序栈,链栈", 2),
    ("DS.03.02", "DS.03", "队列", "顺序队列,链队列,循环队列", 2),
    ("DS.03.03", "DS.03", "栈和队列的应用", "括号匹配,表达式求值,递归", 2),
    ("DS.04", None, "串", "字符串,串结构", 1),
    ("DS.04.01", "DS.04", "串与模式匹配", "字符串,KMP,朴素匹配", 2),
    ("DS.04A", None, "数组和广义表", "数组与广义表,多维数组,广义表", 1),
    ("DS.04.02", "DS.04A", "数组和特殊矩阵", "多维数组,稀疏矩阵,矩阵压缩", 2),
    ("DS.04A.03", "DS.04A", "广义表", "广义表定义,广义表存储,广义表递归", 2),
    ("DS.05", None, "树和二叉树", "树,二叉树", 1),
    ("DS.05.01", "DS.05", "二叉树基础", "二叉树性质,存储结构", 2),
    ("DS.05.02", "DS.05", "二叉树遍历", "先序遍历,中序遍历,后序遍历,层序遍历", 2),
    ("DS.05.03", "DS.05", "树的应用", "哈夫曼树,二叉搜索树,堆", 2),
    ("DS.05.04", "DS.05", "树和森林", "树的存储,森林转换,森林遍历", 2),
    ("DS.05.05", "DS.05", "线索、回溯与树的计数", "线索二叉树,回溯法,树的计数", 2),
    ("DS.06", None, "图", "图结构,图论", 1),
    ("DS.06.01", "DS.06", "图的存储", "邻接矩阵,邻接表", 2),
    ("DS.06.02", "DS.06", "图的遍历", "深度优先,广度优先,DFS,BFS", 2),
    ("DS.06.03", "DS.06", "图的典型算法", "最小生成树,最短路径,拓扑排序,关键路径", 2),
    ("DS.06.04", "DS.06", "图的连通性", "连通分量,强连通分量,关节点,重连通分量", 2),
    ("DS.07", None, "查找", "检索,搜索", 1),
    ("DS.07.01", "DS.07", "静态查找", "顺序查找,折半查找,二分查找", 2),
    ("DS.07.02", "DS.07", "树表查找", "二叉排序树,平衡树,B树", 2),
    ("DS.07.03", "DS.07", "散列查找", "哈希表,散列表,冲突处理", 2),
    ("DS.08", None, "排序", "内部排序,外部排序", 1),
    ("DS.08.01", "DS.08", "基础排序", "插入排序,交换排序,选择排序", 2),
    ("DS.08.02", "DS.08", "高效排序", "希尔排序,快速排序,堆排序,归并排序", 2),
    ("DS.08.03", "DS.08", "排序分析", "稳定性,复杂度比较,外部排序", 2),
    ("DS.08.04", "DS.08", "基数排序", "多关键字排序,链式基数排序", 2),
    ("DS.09", None, "动态存储管理", "内存管理,动态内存,存储管理", 1),
    ("DS.09.01", "DS.09", "空间分配与回收", "可利用空间表,首次适应,最佳适应,边界标识法", 2),
    ("DS.09.02", "DS.09", "伙伴系统", "伙伴分配,伙伴回收", 2),
    ("DS.09.03", "DS.09", "垃圾收集与存储紧缩", "无用单元收集,垃圾回收,存储紧缩", 2),
    ("DS.10", None, "外部排序", "外排序,磁盘排序", 1),
    ("DS.10.01", "DS.10", "外部归并", "多路平衡归并,置换选择,最佳归并树", 2),
    ("DS.11", None, "文件", "文件结构,文件组织", 1),
    ("DS.11.01", "DS.11", "文件基础与顺序文件", "文件基本概念,顺序文件", 2),
    ("DS.11.02", "DS.11", "索引文件", "索引文件,ISAM,VSAM", 2),
    ("DS.11.03", "DS.11", "直接存取与多关键字文件", "散列文件,多重表文件,倒排文件", 2),
]

POINTS = [
    ("DS.CONCEPT", "DS.01.01", "数据结构的基本概念", "数据、数据元素、数据对象及其关系", 1, 35),
    ("DS.LOGICAL", "DS.01.01", "逻辑结构与存储结构", "区分逻辑组织与物理存储方式", 2, 40),
    ("DS.ADT", "DS.01.01", "抽象数据类型", "用数据对象、关系和操作描述抽象数据类型", 2, 40),
    ("DS.ALGORITHM", "DS.01.02", "算法及其特性", "理解算法的输入、输出、确定性和有限性", 1, 30),
    ("DS.COMPLEXITY", "DS.01.02", "时间复杂度与空间复杂度", "使用渐进记号分析算法资源开销", 3, 75),
    ("DS.LINEAR.DEF", "DS.02.01", "线性表的定义与操作", "理解线性表并描述基本操作", 2, 45),
    ("DS.SEQLIST", "DS.02.01", "顺序表", "使用连续空间实现线性表并分析操作复杂度", 2, 60),
    ("DS.LINKED", "DS.02.02", "单链表", "使用结点和指针实现线性表", 3, 75),
    ("DS.DLINKED", "DS.02.02", "双链表与循环链表", "掌握双向及循环链接结构", 3, 60),
    ("DS.STACK.DEF", "DS.03.01", "栈的定义与基本操作", "理解后进先出及入栈、出栈操作", 2, 45),
    ("DS.STACK.IMPL", "DS.03.01", "顺序栈与链栈", "比较栈的两种存储实现", 3, 60),
    ("DS.QUEUE.DEF", "DS.03.02", "队列的定义与基本操作", "理解先进先出及入队、出队操作", 2, 45),
    ("DS.QUEUE.IMPL", "DS.03.02", "循环队列与链队列", "实现队列并处理假溢出问题", 3, 70),
    ("DS.STACK.APP", "DS.03.03", "栈的典型应用", "括号匹配、表达式求值与递归调用", 3, 75),
    ("DS.STRING", "DS.04.01", "串的基本操作", "理解字符串存储和常用操作", 2, 45),
    ("DS.KMP", "DS.04.01", "KMP模式匹配", "利用前缀信息改进字符串匹配", 4, 90),
    ("DS.ARRAY", "DS.04.02", "多维数组的存储", "计算多维数组元素地址", 3, 55),
    ("DS.SPARSE", "DS.04.02", "特殊矩阵与稀疏矩阵", "使用压缩方式存储矩阵", 3, 70),
    ("DS.TREE.DEF", "DS.05.01", "树与二叉树的基本概念", "理解树的层次结构和常用术语", 2, 50),
    ("DS.BTREE.PROPERTY", "DS.05.01", "二叉树性质与存储", "掌握二叉树性质、顺序存储和链式存储", 3, 70),
    ("DS.BTREE.TRAVERSE", "DS.05.02", "二叉树遍历", "实现先序、中序、后序和层序遍历", 3, 90),
    ("DS.BST", "DS.05.03", "二叉搜索树", "实现动态查找并分析性能", 3, 75),
    ("DS.HEAP", "DS.05.03", "堆与优先队列", "掌握完全二叉树上的堆操作", 4, 80),
    ("DS.HUFFMAN", "DS.05.03", "哈夫曼树与编码", "构造最优前缀编码", 3, 70),
    ("DS.GRAPH.DEF", "DS.06.01", "图的基本概念", "理解顶点、边、路径、连通性和度", 2, 45),
    ("DS.GRAPH.STORE", "DS.06.01", "邻接矩阵与邻接表", "选择并实现图的存储结构", 3, 70),
    ("DS.DFS", "DS.06.02", "深度优先遍历", "使用递归或栈遍历图", 3, 65),
    ("DS.BFS", "DS.06.02", "广度优先遍历", "使用队列按层次遍历图", 3, 65),
    ("DS.MST", "DS.06.03", "最小生成树", "掌握Prim和Kruskal算法思想", 4, 90),
    ("DS.SHORTEST", "DS.06.03", "最短路径", "掌握Dijkstra及Floyd算法思想", 4, 100),
    ("DS.TOPO", "DS.06.03", "拓扑排序与关键路径", "处理有向无环图中的工程问题", 4, 100),
    ("DS.SEARCH.SEQ", "DS.07.01", "顺序查找", "分析线性扫描查找", 1, 30),
    ("DS.SEARCH.BINARY", "DS.07.01", "折半查找", "在有序表中进行二分查找", 2, 50),
    ("DS.BALANCED", "DS.07.02", "平衡二叉树", "理解旋转和平衡维护", 4, 90),
    ("DS.BTREE", "DS.07.02", "B树与B+树", "理解外存索引结构", 4, 80),
    ("DS.HASH", "DS.07.03", "散列表", "设计散列函数并处理冲突", 3, 80),
    ("DS.INSERTSORT", "DS.08.01", "直接插入排序", "实现插入排序并分析复杂度", 2, 45),
    ("DS.BUBBLE", "DS.08.01", "冒泡排序", "实现交换排序并分析复杂度", 2, 40),
    ("DS.SELECT", "DS.08.01", "简单选择排序", "实现选择排序并分析复杂度", 2, 40),
    ("DS.SHELL", "DS.08.02", "希尔排序", "理解分组插入与增量序列", 3, 60),
    ("DS.QUICK", "DS.08.02", "快速排序", "掌握划分和递归过程", 4, 85),
    ("DS.HEAPSORT", "DS.08.02", "堆排序", "利用堆完成选择排序", 4, 80),
    ("DS.MERGE", "DS.08.02", "归并排序", "理解分治与合并过程", 4, 80),
    ("DS.SORT.COMPARE", "DS.08.03", "排序算法比较", "比较复杂度、稳定性和适用场景", 3, 70),
]

# Fine-grained concepts align the reusable OpenDSA pool with the chapter and
# subsection granularity used by the supplied Chinese university textbook.
FINE_POINTS = [
    ("DS.DATA.TERMS", "DS.01.01", "数据、数据元素与数据对象", "区分数据、数据元素、数据项和数据对象", 1, 25),
    ("DS.ADT.REP", "DS.01.01", "抽象数据类型的表示与实现", "用三元组和操作接口表示并实现抽象数据类型", 2, 40),
    ("DS.ALG.REQUIREMENTS", "DS.01.02", "算法设计的要求", "理解正确性、可读性、健壮性与效率要求", 2, 30),
    ("DS.ALG.EFFICIENCY", "DS.01.02", "算法效率的度量", "使用时间频度和渐进量级度量算法效率", 3, 55),

    ("DS.LIST.TYPE", "DS.02.01", "线性表的类型定义", "描述线性表的数据对象、关系和基本操作", 2, 35),
    ("DS.SEQLIST.REP", "DS.02.01", "线性表的顺序表示和实现", "实现顺序表的初始化、插入、删除和查找", 3, 65),
    ("DS.LINKED.REP", "DS.02.02", "线性表的链式表示和实现", "实现链表结点、头结点和基本操作", 3, 75),
    ("DS.CIRCULAR", "DS.02.02", "循环链表", "掌握循环链表结构及合并操作", 3, 45),
    ("DS.POLYNOMIAL", "DS.02.02", "一元多项式的表示及相加", "使用链式结构表示并合并一元多项式", 3, 60),

    ("DS.STACK.CONVERT", "DS.03.03", "数制转换", "使用栈完成不同进制之间的转换", 2, 35),
    ("DS.STACK.PAREN", "DS.03.03", "括号匹配", "使用栈检验表达式中的括号配对", 2, 35),
    ("DS.STACK.LINEEDIT", "DS.03.03", "行编辑程序", "利用栈处理退格和行撤销操作", 2, 30),
    ("DS.STACK.MAZE", "DS.03.03", "迷宫求解", "使用栈保存搜索路径并完成回溯", 3, 60),
    ("DS.STACK.EXPR", "DS.03.03", "表达式求值", "使用运算符栈和操作数栈计算表达式", 4, 75),
    ("DS.RECURSION.IMPL", "DS.03.03", "栈与递归的实现", "理解递归调用栈、参数和返回地址", 3, 60),
    ("DS.EVENT.SIM", "DS.03.02", "离散事件模拟", "使用队列组织事件并模拟排队过程", 4, 75),

    ("DS.STRING.FIXED", "DS.04.01", "串的定长顺序存储", "使用定长数组表示字符串", 2, 35),
    ("DS.STRING.HEAP", "DS.04.01", "串的堆分配存储", "使用动态空间保存变长字符串", 3, 45),
    ("DS.STRING.BLOCK", "DS.04.01", "串的块链存储", "使用链式块结构保存字符串", 3, 45),
    ("DS.STRING.NAIVE", "DS.04.01", "朴素模式匹配", "实现定位函数并分析朴素匹配过程", 2, 45),
    ("DS.STRING.EDITOR", "DS.04.01", "文本编辑", "综合使用串操作完成文本编辑", 3, 55),
    ("DS.STRING.INDEX", "DS.04.01", "词索引表", "扫描文本并建立单词到位置的索引", 3, 60),

    ("DS.ARRAY.DEF", "DS.04.02", "数组的定义", "理解数组维度、下标和元素关系", 2, 30),
    ("DS.ARRAY.SEQ", "DS.04.02", "数组的顺序表示和实现", "计算多维数组的行优先或列优先地址", 3, 55),
    ("DS.MATRIX.SPECIAL", "DS.04.02", "特殊矩阵的压缩存储", "压缩存储对称、三角和带状矩阵", 3, 55),
    ("DS.MATRIX.SPARSE", "DS.04.02", "稀疏矩阵的压缩存储", "使用三元组表或十字链表表示稀疏矩阵", 4, 75),
    ("DS.GLIST.DEF", "DS.04A.03", "广义表的定义", "理解广义表、表头、表尾、长度和深度", 3, 45),
    ("DS.GLIST.STORE", "DS.04A.03", "广义表的存储结构", "使用头尾链表或扩展线性链表表示广义表", 4, 65),
    ("DS.GLIST.RECUR", "DS.04A.03", "广义表的递归算法", "递归求深度、复制并建立广义表", 4, 80),
    ("DS.GLIST.POLY", "DS.04A.03", "多元多项式的表示", "使用广义表表示多元多项式", 4, 60),

    ("DS.THREADED", "DS.05.02", "线索二叉树", "利用空指针域保存遍历前驱和后继", 4, 70),
    ("DS.TREE.STORE", "DS.05.04", "树的存储结构", "掌握双亲、孩子和孩子兄弟表示法", 3, 60),
    ("DS.FOREST.CONVERT", "DS.05.04", "森林与二叉树的转换", "在树、森林和二叉树之间转换", 3, 60),
    ("DS.FOREST.TRAVERSE", "DS.05.04", "树和森林的遍历", "掌握树和森林的先根、后根遍历", 3, 55),
    ("DS.TREE.EQUIV", "DS.05.04", "树与等价问题", "使用集合和树处理等价类", 4, 70),
    ("DS.BACKTRACK", "DS.05.05", "回溯法与树的遍历", "把解空间组织成树并进行回溯搜索", 4, 80),
    ("DS.TREE.COUNT", "DS.05.05", "树的计数", "分析不同二叉树形态的数量", 5, 70),

    ("DS.GRAPH.ARRAY", "DS.06.01", "图的数组表示法", "使用邻接矩阵和关联矩阵表示图", 2, 45),
    ("DS.GRAPH.ADJLIST", "DS.06.01", "图的邻接表", "使用顶点表和边结点表示图", 3, 50),
    ("DS.GRAPH.ORTHO", "DS.06.01", "图的十字链表", "使用十字链表表示有向图", 4, 55),
    ("DS.GRAPH.MULTILIST", "DS.06.01", "图的邻接多重表", "使用邻接多重表表示无向图", 4, 55),
    ("DS.GRAPH.COMPONENT", "DS.06.04", "无向图的连通分量和生成树", "遍历无向图并构造生成森林", 3, 60),
    ("DS.GRAPH.SCC", "DS.06.04", "有向图的强连通分量", "求解有向图的强连通分量", 5, 80),
    ("DS.GRAPH.ARTICULATION", "DS.06.04", "关节点和重连通分量", "识别关节点并分析重连通性", 5, 85),
    ("DS.CRITICAL", "DS.06.03", "关键路径", "在AOE网中计算关键活动和工期", 4, 85),

    ("DS.MEM.FREELIST", "DS.09.01", "可利用空间表", "组织可分配空闲块并维护空闲链表", 3, 45),
    ("DS.MEM.ALLOC", "DS.09.01", "动态空间分配方法", "比较首次、循环首次、最佳和最差适应策略", 4, 70),
    ("DS.MEM.BOUNDARY", "DS.09.01", "边界标识法", "利用边界标记完成空间分配与合并回收", 4, 75),
    ("DS.MEM.BUDDY.ALLOC", "DS.09.02", "伙伴系统的分配", "按2的幂次拆分伙伴块完成分配", 4, 65),
    ("DS.MEM.BUDDY.FREE", "DS.09.02", "伙伴系统的回收", "识别并合并空闲伙伴块", 4, 60),
    ("DS.MEM.GC", "DS.09.03", "无用单元收集", "标记可达对象并回收无用单元", 4, 75),
    ("DS.MEM.COMPACT", "DS.09.03", "存储紧缩", "移动对象并合并零散空闲空间", 4, 60),
    ("DS.MEM.PERF", "DS.09.01", "动态存储管理性能", "分析碎片、利用率和分配代价", 4, 55),

    ("DS.SEARCH.ORDERED", "DS.07.01", "有序表的查找", "利用有序性进行折半或分块查找", 2, 45),
    ("DS.SEARCH.STATICTREE", "DS.07.01", "静态树表的查找", "根据查找概率构造次优静态查找树", 4, 60),
    ("DS.SEARCH.INDEXSEQ", "DS.07.01", "索引顺序表的查找", "先查索引再在数据块内顺序查找", 3, 50),
    ("DS.TRIE", "DS.07.02", "键树", "使用数字搜索树或Trie组织关键字", 4, 70),
    ("DS.HASH.FUNC", "DS.07.03", "哈希函数的构造", "使用除留余数、数字分析等方法构造哈希函数", 3, 55),
    ("DS.HASH.COLLISION", "DS.07.03", "哈希冲突处理", "使用开放定址或链地址处理冲突", 4, 65),
    ("DS.HASH.ANALYSIS", "DS.07.03", "哈希表查找分析", "分析装填因子与平均查找长度", 4, 60),

    ("DS.SORT.OVERVIEW", "DS.08.03", "内部排序概述", "理解排序记录、关键字、稳定性和内部排序", 2, 35),
    ("DS.TREESELECT", "DS.08.01", "树形选择排序", "使用锦标赛树反复选择最小记录", 4, 55),
    ("DS.RADIX.MULTI", "DS.08.04", "多关键字排序", "按主次关键字组织排序过程", 3, 50),
    ("DS.RADIX.LINKED", "DS.08.04", "链式基数排序", "通过分配和收集完成链式基数排序", 4, 70),
    ("DS.SORT.STABILITY", "DS.08.03", "排序稳定性与适用条件", "比较各种内部排序的稳定性和使用场景", 3, 55),

    ("DS.EXT.ACCESS", "DS.10", "外存信息的存取", "理解磁盘块、缓冲区和外存访问代价", 3, 50),
    ("DS.EXT.MERGE", "DS.10.01", "多路平衡归并", "使用多个归并段减少外存读写趟数", 4, 80),
    ("DS.EXT.REPLACE", "DS.10.01", "置换选择排序", "利用选择树生成更长的初始归并段", 5, 75),
    ("DS.EXT.OPTIMAL", "DS.10.01", "最佳归并树", "使用带权路径长度安排归并顺序", 5, 65),

    ("DS.FILE.CONCEPT", "DS.11.01", "文件的基本概念", "理解记录、关键字、物理文件和逻辑文件", 2, 40),
    ("DS.FILE.SEQUENTIAL", "DS.11.01", "顺序文件", "按记录顺序组织和访问文件", 2, 45),
    ("DS.FILE.INDEXED", "DS.11.02", "索引文件", "建立索引表以加速文件访问", 3, 55),
    ("DS.FILE.ISAM", "DS.11.02", "ISAM文件", "理解静态索引顺序访问方法", 4, 65),
    ("DS.FILE.VSAM", "DS.11.02", "VSAM文件", "理解虚拟存储访问方法和控制区间", 4, 65),
    ("DS.FILE.HASH", "DS.11.03", "散列文件", "使用散列地址直接访问外存记录", 4, 60),
    ("DS.FILE.MULTIKEY", "DS.11.03", "多关键字文件", "使用多重表或倒排表支持多关键字检索", 4, 70),
]

ALL_POINTS = POINTS + FINE_POINTS

POINT_ALIASES = {
    "DS.CONCEPT": "什么是数据结构,数据结构",
    "DS.LOGICAL": "基本概念和术语,逻辑结构,存储结构",
    "DS.ALGORITHM": "算法",
    "DS.COMPLEXITY": "算法分析,算法效率,存储空间需求",
    "DS.SEQLIST": "顺序表示,顺序实现",
    "DS.LINKED": "线性链表,链式表示",
    "DS.DLINKED": "双向链表",
    "DS.STACK.APP": "栈的应用举例",
    "DS.STRING": "串类型定义,串的表示和实现",
    "DS.KMP": "模式匹配的改进算法",
    "DS.SPARSE": "矩阵的压缩存储",
    "DS.TREE.DEF": "树的定义和基本术语",
    "DS.BTREE.PROPERTY": "二叉树的定义,二叉树的性质,二叉树的存储结构",
    "DS.BTREE.TRAVERSE": "遍历二叉树",
    "DS.HUFFMAN": "赫夫曼树,最优二叉树,赫夫曼编码",
    "DS.GRAPH.DEF": "图的定义和术语",
    "DS.GRAPH.STORE": "图的存储结构",
    "DS.DFS": "深度优先搜索",
    "DS.BFS": "广度优先搜索",
    "DS.MST": "最小生成树",
    "DS.SHORTEST": "最短路径,单源最短路径,每对顶点最短路径",
    "DS.TOPO": "拓扑排序",
    "DS.SEARCH.SEQ": "顺序表的查找",
    "DS.SEARCH.BINARY": "有序表的查找,折半查找",
    "DS.BALANCED": "平衡二叉树",
    "DS.BTREE": "B-树和B+树,B树与B+树",
    "DS.HASH": "什么是哈希表,哈希表",
    "DS.INSERTSORT": "直接插入排序",
    "DS.SELECT": "简单选择排序",
    "DS.SORT.COMPARE": "各种内部排序方法的比较讨论",
}

RELATIONS = [
    ("DS.CONCEPT", "DS.LOGICAL"), ("DS.LOGICAL", "DS.ADT"), ("DS.ALGORITHM", "DS.COMPLEXITY"),
    ("DS.ADT", "DS.LINEAR.DEF"), ("DS.LINEAR.DEF", "DS.SEQLIST"), ("DS.LINEAR.DEF", "DS.LINKED"),
    ("DS.LINKED", "DS.DLINKED"), ("DS.SEQLIST", "DS.STACK.IMPL"), ("DS.LINKED", "DS.STACK.IMPL"),
    ("DS.STACK.DEF", "DS.STACK.IMPL"), ("DS.QUEUE.DEF", "DS.QUEUE.IMPL"),
    ("DS.STACK.IMPL", "DS.STACK.APP"), ("DS.STRING", "DS.KMP"), ("DS.ARRAY", "DS.SPARSE"),
    ("DS.TREE.DEF", "DS.BTREE.PROPERTY"), ("DS.BTREE.PROPERTY", "DS.BTREE.TRAVERSE"),
    ("DS.BTREE.TRAVERSE", "DS.BST"), ("DS.BTREE.PROPERTY", "DS.HEAP"),
    ("DS.BTREE.PROPERTY", "DS.HUFFMAN"), ("DS.GRAPH.DEF", "DS.GRAPH.STORE"),
    ("DS.GRAPH.STORE", "DS.DFS"), ("DS.GRAPH.STORE", "DS.BFS"), ("DS.DFS", "DS.TOPO"),
    ("DS.GRAPH.STORE", "DS.MST"), ("DS.GRAPH.STORE", "DS.SHORTEST"),
    ("DS.SEARCH.SEQ", "DS.SEARCH.BINARY"), ("DS.BST", "DS.BALANCED"),
    ("DS.BALANCED", "DS.BTREE"), ("DS.COMPLEXITY", "DS.SORT.COMPARE"),
    ("DS.INSERTSORT", "DS.SHELL"), ("DS.HEAP", "DS.HEAPSORT"),
    ("DS.COMPLEXITY", "DS.QUICK"), ("DS.COMPLEXITY", "DS.MERGE"),
]

FINE_RELATIONS = [
    ("DS.CONCEPT", "DS.DATA.TERMS"), ("DS.DATA.TERMS", "DS.ADT.REP"),
    ("DS.ALGORITHM", "DS.ALG.REQUIREMENTS"), ("DS.ALG.REQUIREMENTS", "DS.ALG.EFFICIENCY"),
    ("DS.ALG.EFFICIENCY", "DS.COMPLEXITY"),
    ("DS.LINEAR.DEF", "DS.LIST.TYPE"), ("DS.LIST.TYPE", "DS.SEQLIST.REP"),
    ("DS.LIST.TYPE", "DS.LINKED.REP"), ("DS.LINKED.REP", "DS.CIRCULAR"),
    ("DS.LINKED.REP", "DS.DLINKED"), ("DS.LINKED.REP", "DS.POLYNOMIAL"),
    ("DS.STACK.DEF", "DS.STACK.CONVERT"), ("DS.STACK.DEF", "DS.STACK.PAREN"),
    ("DS.STACK.DEF", "DS.STACK.LINEEDIT"), ("DS.STACK.IMPL", "DS.STACK.MAZE"),
    ("DS.STACK.IMPL", "DS.STACK.EXPR"), ("DS.STACK.IMPL", "DS.RECURSION.IMPL"),
    ("DS.QUEUE.IMPL", "DS.EVENT.SIM"),
    ("DS.STRING", "DS.STRING.FIXED"), ("DS.STRING", "DS.STRING.HEAP"),
    ("DS.STRING", "DS.STRING.BLOCK"), ("DS.STRING", "DS.STRING.NAIVE"),
    ("DS.STRING.NAIVE", "DS.KMP"), ("DS.STRING", "DS.STRING.EDITOR"),
    ("DS.STRING", "DS.STRING.INDEX"),
    ("DS.ARRAY.DEF", "DS.ARRAY.SEQ"), ("DS.ARRAY.SEQ", "DS.MATRIX.SPECIAL"),
    ("DS.ARRAY.SEQ", "DS.MATRIX.SPARSE"), ("DS.GLIST.DEF", "DS.GLIST.STORE"),
    ("DS.GLIST.STORE", "DS.GLIST.RECUR"), ("DS.GLIST.STORE", "DS.GLIST.POLY"),
    ("DS.BTREE.TRAVERSE", "DS.THREADED"), ("DS.TREE.DEF", "DS.TREE.STORE"),
    ("DS.TREE.STORE", "DS.FOREST.CONVERT"), ("DS.FOREST.CONVERT", "DS.FOREST.TRAVERSE"),
    ("DS.TREE.STORE", "DS.TREE.EQUIV"), ("DS.BTREE.TRAVERSE", "DS.BACKTRACK"),
    ("DS.BTREE.PROPERTY", "DS.TREE.COUNT"),
    ("DS.GRAPH.DEF", "DS.GRAPH.ARRAY"), ("DS.GRAPH.DEF", "DS.GRAPH.ADJLIST"),
    ("DS.GRAPH.ADJLIST", "DS.GRAPH.ORTHO"), ("DS.GRAPH.ADJLIST", "DS.GRAPH.MULTILIST"),
    ("DS.DFS", "DS.GRAPH.COMPONENT"), ("DS.DFS", "DS.GRAPH.SCC"),
    ("DS.DFS", "DS.GRAPH.ARTICULATION"), ("DS.TOPO", "DS.CRITICAL"),
    ("DS.MEM.FREELIST", "DS.MEM.ALLOC"), ("DS.MEM.ALLOC", "DS.MEM.BOUNDARY"),
    ("DS.MEM.ALLOC", "DS.MEM.BUDDY.ALLOC"), ("DS.MEM.BUDDY.ALLOC", "DS.MEM.BUDDY.FREE"),
    ("DS.MEM.FREELIST", "DS.MEM.GC"), ("DS.MEM.GC", "DS.MEM.COMPACT"),
    ("DS.MEM.ALLOC", "DS.MEM.PERF"),
    ("DS.SEARCH.SEQ", "DS.SEARCH.ORDERED"), ("DS.SEARCH.ORDERED", "DS.SEARCH.STATICTREE"),
    ("DS.SEARCH.ORDERED", "DS.SEARCH.INDEXSEQ"), ("DS.BTREE", "DS.TRIE"),
    ("DS.HASH", "DS.HASH.FUNC"), ("DS.HASH.FUNC", "DS.HASH.COLLISION"),
    ("DS.HASH.COLLISION", "DS.HASH.ANALYSIS"),
    ("DS.SORT.OVERVIEW", "DS.INSERTSORT"), ("DS.SELECT", "DS.TREESELECT"),
    ("DS.SORT.OVERVIEW", "DS.RADIX.MULTI"), ("DS.RADIX.MULTI", "DS.RADIX.LINKED"),
    ("DS.SORT.OVERVIEW", "DS.SORT.STABILITY"),
    ("DS.EXT.ACCESS", "DS.EXT.MERGE"), ("DS.EXT.MERGE", "DS.EXT.REPLACE"),
    ("DS.EXT.MERGE", "DS.EXT.OPTIMAL"),
    ("DS.FILE.CONCEPT", "DS.FILE.SEQUENTIAL"), ("DS.FILE.CONCEPT", "DS.FILE.INDEXED"),
    ("DS.FILE.INDEXED", "DS.FILE.ISAM"), ("DS.FILE.ISAM", "DS.FILE.VSAM"),
    ("DS.FILE.CONCEPT", "DS.FILE.HASH"), ("DS.FILE.INDEXED", "DS.FILE.MULTIKEY"),
]

ALL_RELATIONS = RELATIONS + FINE_RELATIONS


def seed_data_structures_template(db: Session) -> CurriculumTemplate:
    template = db.scalar(select(CurriculumTemplate).where(CurriculumTemplate.code == TEMPLATE_CODE))
    if not template:
        template = CurriculumTemplate(code=TEMPLATE_CODE, name="数据结构细粒度理论资源库",
                                      version="2.0")
        db.add(template); db.flush()
    template.name = "数据结构细粒度理论资源库"
    template.version = "2.0"
    template.description = "面向本校数据结构教材细分章节的可复用理论资源池；教材目录决定课程结构。"
    template.source_note = "理论正文来自 OpenDSA；中文知识点按本校教材细化。当前范围只含理论正文。"
    topic_existing = {row.canonical_key: row for row in db.scalars(select(CanonicalTopic).where(
        CanonicalTopic.template_id == template.id)).all()}
    for order, (key, parent, title, aliases, level) in enumerate(TOPICS):
        row = topic_existing.get(key)
        if not row:
            row = CanonicalTopic(template_id=template.id, canonical_key=key)
            db.add(row)
        row.parent_key, row.title, row.aliases = parent, title, aliases
        row.level, row.sort_order = level, order
    point_existing = {row.canonical_key: row for row in db.scalars(select(CanonicalKnowledgePoint).where(
        CanonicalKnowledgePoint.template_id == template.id)).all()}
    for order, (key, topic, name, summary, difficulty, minutes) in enumerate(ALL_POINTS):
        row = point_existing.get(key)
        if not row:
            row = CanonicalKnowledgePoint(template_id=template.id, canonical_key=key)
            db.add(row)
        row.topic_key, row.name, row.summary = topic, name, summary
        row.aliases, row.point_type = POINT_ALIASES.get(key, ""), "core"
        row.difficulty, row.estimated_minutes, row.sort_order = difficulty, minutes, order
    relation_existing = {(row.from_key, row.to_key, row.relation_type) for row in db.scalars(select(
        CanonicalRelation).where(CanonicalRelation.template_id == template.id)).all()}
    for source, target in ALL_RELATIONS:
        if (source, target, "prerequisite") not in relation_existing:
            db.add(CanonicalRelation(template_id=template.id, from_key=source, to_key=target))
    db.commit(); db.refresh(template)
    return template


def apply_template(db: Session, course_id: int, template: CurriculumTemplate) -> dict:
    existing_binding = db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == course_id,
        CourseTemplateBinding.template_id == template.id,
    ))
    if existing_binding:
        resource_book = db.get(Book, existing_binding.template_book_id)
        if resource_book:
            resource_book.status = "resource_pool"
            resource_book.parse_message = "OpenDSA 理论资源池；上传本校教材目录后生成本课程结构"
        has_outline = db.scalar(select(CourseOutlineBinding).where(
            CourseOutlineBinding.course_id == course_id,
            CourseOutlineBinding.active.is_(True),
        ))
        if not has_outline:
            for item in db.scalars(select(CourseKnowledgeBinding).where(
                CourseKnowledgeBinding.course_id == course_id)).all():
                item.coverage_status = "resource_only"
                kp = db.get(KnowledgePoint, item.kp_id)
                if kp:
                    kp.approved = False
                req = db.scalar(select(CourseRequirement).where(
                    CourseRequirement.course_id == course_id, CourseRequirement.kp_id == item.kp_id))
                if req:
                    req.included_in_exam = False
        db.commit()
        return {"created": 0, "reused": 0, "resource_points": len(ALL_POINTS),
                "already_applied": True}
    book = Book(course_id=course_id, title="OpenDSA 理论资源库", author="OpenDSA / StudyShip",
                edition=template.version, file_path="", file_hash=f"template:{template.code}:{course_id}",
                status="resource_pool", parse_message="理论资源池已载入；上传本校教材目录后生成本课程结构")
    db.add(book); db.flush()
    db.add(CourseTemplateBinding(course_id=course_id, template_id=template.id, template_book_id=book.id))
    db.commit()
    return {"created": 0, "reused": 0, "topics": 0, "relations": 0,
            "resource_points": len(ALL_POINTS), "already_applied": False}


def _title_core(value: str) -> str:
    value = re.sub(r"^\s*(?:第[一二三四五六七八九十百0-9]+[章节篇]|\d+(?:\.\d+){0,3})\s*[、.．：:]?\s*", "", value)
    value = re.sub(r"[.．…·\s]+\d+\s*$", "", value)
    value = re.sub(r"[\s，。；、:：()（）\-—]", "", value).lower()
    return value


def _name_score(title: str, name: str, aliases: str = "") -> float:
    left = _title_core(title)
    candidates = [_title_core(name)] + [_title_core(x) for x in aliases.split(",") if x.strip()]
    best = 0.0
    for right in candidates:
        if not left or not right:
            continue
        if left in right or right in left:
            best = max(best, min(len(left), len(right)) / max(len(left), len(right)))
        best = max(best, SequenceMatcher(None, left, right).ratio())
    return best


def _topic_score(title: str, topic: CanonicalTopic) -> float:
    return _name_score(title, topic.title, topic.aliases)


def _best_match(title: str, topics: list[CanonicalTopic],
                points: list[CanonicalKnowledgePoint]) -> tuple[str, float]:
    topic_score, best_topic = max(((_topic_score(title, topic), topic) for topic in topics),
                                  key=lambda x: x[0], default=(0.0, None))
    point_score, best_point = max(((_name_score(title, point.name, point.aliases), point)
                                   for point in points), key=lambda x: x[0], default=(0.0, None))
    choose_point = bool(best_point and point_score >= 0.58 and point_score > topic_score + 0.04)
    score = point_score if choose_point else topic_score
    match_key = f"KP:{best_point.canonical_key}" if choose_point else (
        best_topic.canonical_key if best_topic else "")
    return (match_key if match_key and score >= 0.52 else "", score)


def align_outline(db: Session, outline: OutlineDocument, headings: list[tuple[int, str, int]],
                  template: CurriculumTemplate) -> dict:
    topics = db.scalars(select(CanonicalTopic).where(
        CanonicalTopic.template_id == template.id).order_by(CanonicalTopic.sort_order)).all()
    points = db.scalars(select(CanonicalKnowledgePoint).where(
        CanonicalKnowledgePoint.template_id == template.id).order_by(
        CanonicalKnowledgePoint.sort_order)).all()
    stack: dict[int, OutlineEntry] = {}
    matched = 0
    for order, (level, title, _page) in enumerate(headings):
        match_key, score = _best_match(title, topics, points)
        accepted = bool(match_key)
        parent = stack.get(level - 1)
        entry = OutlineEntry(outline_id=outline.id, parent_id=parent.id if parent else None,
                             title=title[:240], normalized_title=_title_core(title), level=min(level, 4),
                             sort_order=order, matched_topic_key=match_key if accepted else "",
                             confidence=round(score, 3), review_status="suggested" if accepted else "unmatched")
        db.add(entry); db.flush(); stack[level] = entry
        for depth in list(stack):
            if depth > level:
                del stack[depth]
        if accepted:
            matched += 1
    build_course_from_outline(db, outline, template)
    outline.status = "needs_review"
    outline.parse_message = f"识别 {len(headings)} 条目录，自动匹配 {matched} 条；课程层级以本目录为准"
    db.commit()
    return {"entries": len(headings), "matched": matched, "message": outline.parse_message}


def rematch_outline(db: Session, outline: OutlineDocument,
                    template: CurriculumTemplate) -> dict:
    topics = list(db.scalars(select(CanonicalTopic).where(
        CanonicalTopic.template_id == template.id).order_by(CanonicalTopic.sort_order)).all())
    points = list(db.scalars(select(CanonicalKnowledgePoint).where(
        CanonicalKnowledgePoint.template_id == template.id).order_by(
        CanonicalKnowledgePoint.sort_order)).all())
    entries = db.scalars(select(OutlineEntry).where(
        OutlineEntry.outline_id == outline.id).order_by(OutlineEntry.sort_order)).all()
    matched = 0
    for entry in entries:
        key, score = _best_match(entry.title, topics, points)
        entry.matched_topic_key = key
        entry.confidence = round(score, 3)
        entry.review_status = "suggested" if key else "unmatched"
        matched += bool(key)
    build_course_from_outline(db, outline, template)
    outline.parse_message = (f"细粒度资源库重新匹配：{len(entries)} 条目录，"
                             f"自动匹配 {matched} 条")
    db.commit()
    return {"entries": len(entries), "matched": matched}


def refresh_outline_coverage(db: Session, outline: OutlineDocument, template: CurriculumTemplate) -> None:
    build_course_from_outline(db, outline, template)


def build_course_from_outline(db: Session, outline: OutlineDocument,
                              template: CurriculumTemplate) -> dict:
    """Materialize a course tree from the uploaded outline, then attach theory points."""
    entries = db.scalars(select(OutlineEntry).where(
        OutlineEntry.outline_id == outline.id).order_by(OutlineEntry.sort_order)).all()
    if not entries:
        return {"topics": 0, "knowledge_points": 0}

    current_outline_binding = db.scalar(select(CourseOutlineBinding).where(
        CourseOutlineBinding.outline_id == outline.id,
        CourseOutlineBinding.active.is_(True),
    ))
    # The outline is the course authority. Older versions stay in the database as history.
    for old in db.scalars(select(CourseOutlineBinding).where(
        CourseOutlineBinding.course_id == outline.course_id,
        CourseOutlineBinding.active.is_(True),
        CourseOutlineBinding.outline_id != outline.id,
    )).all():
        old.active = False
        old_book = db.get(Book, old.book_id)
        if old_book:
            old_book.status = "outline_archived"
    topic_for_entry: dict[int, Topic] = {}
    if current_outline_binding:
        book = db.get(Book, current_outline_binding.book_id)
        existing_topics = db.scalars(select(Topic).where(
            Topic.book_id == book.id).order_by(Topic.sort_order)).all()
        topic_for_entry = {entry.id: topic for entry, topic in zip(entries, existing_topics)}
    else:
        book = Book(course_id=outline.course_id, title=outline.title, author="本校教材目录",
                    file_path=outline.file_path, file_hash=f"outline:{outline.id}:{outline.file_hash}",
                    status="needs_review", parse_message="课程章节由本校目录生成；知识点来自 OpenDSA 理论资源映射")
        db.add(book); db.flush()
        db.add(CourseOutlineBinding(course_id=outline.course_id, outline_id=outline.id,
                                    book_id=book.id, active=True))
        for entry in entries:
            parent = topic_for_entry.get(entry.parent_id or -1)
            topic = Topic(course_id=outline.course_id, book_id=book.id,
                          parent_id=parent.id if parent else None, title=entry.title,
                          level=entry.level, start_page=0, end_page=0, sort_order=entry.sort_order)
            db.add(topic); db.flush()
            topic_for_entry[entry.id] = topic

    canonical_topics = db.scalars(select(CanonicalTopic).where(
        CanonicalTopic.template_id == template.id)).all()
    topic_by_key = {t.canonical_key: t for t in canonical_topics}
    children: dict[str, list[str]] = {}
    for topic in canonical_topics:
        if topic.parent_key:
            children.setdefault(topic.parent_key, []).append(topic.canonical_key)
    matched_entries = {e.matched_topic_key: e for e in entries
                       if e.matched_topic_key and not e.matched_topic_key.startswith("KP:")}
    matched_point_entries = {e.matched_topic_key[3:]: e for e in entries
                             if e.matched_topic_key.startswith("KP:")}
    matched_keys = set(matched_entries)

    selected_topic_keys: set[str] = set()
    for key in matched_keys:
        selected_topic_keys.add(key)
        # A broad chapter imports its descendants only when the uploaded directory
        # has no more specific mapped subsection under that chapter.
        child_keys = children.get(key, [])
        if child_keys and not any(child in matched_keys for child in child_keys):
            selected_topic_keys.update(child_keys)

    points = db.scalars(select(CanonicalKnowledgePoint).where(
        CanonicalKnowledgePoint.template_id == template.id).order_by(
        CanonicalKnowledgePoint.sort_order)).all()
    selected_points = [point for point in points if point.topic_key in selected_topic_keys
                       or point.canonical_key in matched_point_entries]
    existing_bindings = {item.canonical_key: item for item in db.scalars(select(
        CourseKnowledgeBinding).where(CourseKnowledgeBinding.course_id == outline.course_id)).all()}
    kp_by_id = {kp.id: kp for kp in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == outline.course_id)).all()}
    selected_keys: set[str] = set()
    active_kps: dict[str, KnowledgePoint] = {}

    def nearest_entry(topic_key: str) -> OutlineEntry | None:
        if topic_key in matched_entries:
            return matched_entries[topic_key]
        parent = topic_by_key.get(topic_key).parent_key if topic_key in topic_by_key else None
        return matched_entries.get(parent or "")

    for point in selected_points:
        entry = matched_point_entries.get(point.canonical_key) or nearest_entry(point.topic_key)
        if not entry:
            continue
        selected_keys.add(point.canonical_key)
        binding = existing_bindings.get(point.canonical_key)
        kp = kp_by_id.get(binding.kp_id) if binding else None
        if not kp:
            kp = KnowledgePoint(course_id=outline.course_id, topic_id=topic_for_entry[entry.id].id,
                                name=point.name, normalized_name=normalize_name(point.name), summary=point.summary,
                                difficulty=point.difficulty, estimated_minutes=point.estimated_minutes,
                                source_page_start=0, source_page_end=0,
                                source_evidence="OpenDSA 理论资源 + 本校教材目录映射",
                                confidence=max(.7, entry.confidence), approved=False)
            db.add(kp); db.flush()
            binding = CourseKnowledgeBinding(course_id=outline.course_id, kp_id=kp.id,
                                              canonical_key=point.canonical_key)
            db.add(binding); existing_bindings[point.canonical_key] = binding
        kp.topic_id = topic_for_entry[entry.id].id
        binding.coverage_status = "course"
        binding.matched_outline_title = entry.title
        binding.match_confidence = entry.confidence
        req = db.scalar(select(CourseRequirement).where(
            CourseRequirement.course_id == outline.course_id, CourseRequirement.kp_id == kp.id))
        if not req:
            req = CourseRequirement(course_id=outline.course_id, kp_id=kp.id)
            db.add(req)
        req.included_in_exam = True
        active_kps[point.canonical_key] = kp

    # Preserve old mastery through stable canonical keys, but keep unselected
    # OpenDSA concepts out of the active course tree.
    for key, binding in existing_bindings.items():
        if key not in selected_keys:
            binding.coverage_status = "resource_only"
            binding.matched_outline_title = ""
            binding.match_confidence = 0.0
            kp = kp_by_id.get(binding.kp_id)
            if kp:
                kp.topic_id = None
                kp.approved = False
            req = db.scalar(select(CourseRequirement).where(
                CourseRequirement.course_id == outline.course_id,
                CourseRequirement.kp_id == binding.kp_id))
            if req:
                req.included_in_exam = False

    # A leaf that has no canonical match is still a real local course node.
    entry_children = {entry.parent_id for entry in entries if entry.parent_id}
    for entry in entries:
        if entry.id in entry_children or entry.matched_topic_key:
            continue
        path_parts, cursor = [entry.normalized_title], entry
        while cursor.parent_id:
            cursor = next((x for x in entries if x.id == cursor.parent_id), cursor)
            path_parts.append(cursor.normalized_title)
            if not cursor.parent_id:
                break
        local_key = "LOCAL." + hashlib.sha1("/".join(reversed(path_parts)).encode("utf-8")).hexdigest()[:16]
        selected_keys.add(local_key)
        binding = existing_bindings.get(local_key)
        kp = kp_by_id.get(binding.kp_id) if binding else None
        if not kp:
            kp = KnowledgePoint(course_id=outline.course_id, topic_id=topic_for_entry[entry.id].id,
                                name=entry.title, normalized_name=normalize_name(entry.title),
                                summary="本校教材目录中的课程内容，等待教师补充或关联理论资料。",
                                difficulty=2, estimated_minutes=45, confidence=1.0, approved=False,
                                source_evidence="本校教材目录")
            db.add(kp); db.flush()
            binding = CourseKnowledgeBinding(course_id=outline.course_id, kp_id=kp.id,
                                              canonical_key=local_key)
            db.add(binding)
        kp.topic_id = topic_for_entry[entry.id].id
        binding.coverage_status = "course"
        binding.matched_outline_title = entry.title
        binding.match_confidence = 1.0
        active_kps[local_key] = kp
        if not db.scalar(select(CourseRequirement).where(
            CourseRequirement.course_id == outline.course_id, CourseRequirement.kp_id == kp.id)):
            db.add(CourseRequirement(course_id=outline.course_id, kp_id=kp.id))

    existing_rel = {(r.from_kp_id, r.to_kp_id) for r in db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == outline.course_id)).all()}
    for rel in db.scalars(select(CanonicalRelation).where(
        CanonicalRelation.template_id == template.id)).all():
        if rel.from_key in active_kps and rel.to_key in active_kps:
            pair = (active_kps[rel.from_key].id, active_kps[rel.to_key].id)
            if pair not in existing_rel:
                db.add(KnowledgeRelation(course_id=outline.course_id, from_kp_id=pair[0], to_kp_id=pair[1],
                                         relation_type=rel.relation_type, confidence=1.0, approved=False))
    for enrollment in db.scalars(select(Enrollment).where(
        Enrollment.course_id == outline.course_id)).all():
        old = {s.kp_id for s in db.scalars(select(StudentState).where(
            StudentState.student_id == enrollment.student_id)).all()}
        for kp in active_kps.values():
            if kp.id not in old:
                db.add(StudentState(student_id=enrollment.student_id, kp_id=kp.id))
    return {"topics": len(entries), "knowledge_points": len(active_kps)}

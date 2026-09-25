# MDFixer 固定样本：main.o 缺少 config.h（B14 E3）

课程 E3 B 组 MDFixer 样本，对应课件《E3 并行测试基线》第 33、34、35 页。
它是最小的缺失依赖（MD）样本：`main.c` 在编译期读取 `config.h`，但
`Makefile.before` 没有把 `config.h` 声明为 `main.o` 的依赖。

## 为什么这是 MD（缺失依赖）

| 事实 | 证据 |
| --- | --- |
| `main.c` 实际读取 `config.h` | 源码第 8 行 `#include "config.h"`，编译 `main.o` 时必须读取 |
| `Makefile` 未声明该边 | `Makefile.before` 只有 `main.o: main.c`，没有 `config.h` |
| 后果：旧产物被复用 | 只改 `config.h` 后普通 `make` 认为 `main.o` 无需更新，程序仍输出旧值 |
| 对照：完整重建正确 | `make clean && make` 后重新读取 `config.h`，输出新值 |

因此这是**声明依赖**（Makefile 声明的边）**小于实际依赖**（编译期真正读取
的文件）造成的缺失依赖，而不是编译错误，也不是冗余声明（RD）。

## 声明风格：Target（直接列依赖）

样本采用最简单、最直接的 Target 风格：`main.o: main.c`。参考修复保持同一
风格，只在同一行直接追加 `config.h`：

```diff
-main.o: main.c
+main.o: main.c config.h
 	$(CC) -c main.c -o main.o
```

四种课程声明风格（Target / Macro / Hybrid / Implicit）见课件第 34 页；
本样本只实现最基础的 Target 风格，其余风格留待 E8 扩展。

## 文件

| 文件 | 作用 |
| --- | --- |
| `main.c` | 读取 `config.h`，打印 `VALUE` |
| `config.h` | `#define VALUE 1`，行为测试中改为 2、3 |
| `Makefile.before` | 修复前 Makefile（缺少 `config.h`） |
| `Makefile.after` | 参考修复后的 Makefile |
| `reference.patch` | 由 `Makefile.before` 到 `Makefile.after` 的真实 Git 补丁 |
| `md_report.json` | 人工固定 MD 报告（来源 `INSTRUCTOR_ORACLE`） |

## 复现命令

```sh
cp Makefile.before Makefile
make && ./app          # VALUE=1 -> 输出 1
sed -i 's/#define VALUE 1/#define VALUE 2/' config.h
make && ./app          # 期望：仍然输出 1（MD 导致复用旧 main.o）
make clean && make && ./app   # 期望：输出 2（完整重建）

git apply --check reference.patch
git apply reference.patch
sed -i 's/#define VALUE 2/#define VALUE 3/' config.h
make && ./app          # 期望：输出 3（修复后自动重建）
```

真实执行日志、退出码与内容 SHA 见 `e3/evidence/<运行时间>/`。

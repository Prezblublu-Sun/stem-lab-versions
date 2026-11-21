"""物理上对不对。这一组不交给 AI 签：算例和容差由人定，结果由人签。

2026-11 你说“后续的四样……结合文献自己定”，所以这里的算例和线是照文献和旧项目的实测先定下的，都写在 lines.py 一处，
理由和出处在 docs/四样的决定.md。它们等你看过、改过才算数；改线只改 lines.py。

    test_fea.py         Lamé 压配对照（有解析解）；设计 A 和旧系统同一个设计比；界面力和外载平衡；载荷的大小
    test_recon.py       3406 这根骨：自动找的标志点和旧系统核过的参考值差多少；实体的体积、颈部皮质厚度在不在合理范围
    test_surrogate.py   拿旧数据库的结果训练一次：留出误差落在哪一档

这里的测试都标 @pytest.mark.science，平时的检查不跑它们：

    python -m pytest tests/science -m science

要用到旧系统的文件（只读）和 Abaqus；哪样没有，对应的测试就跳过并说明缺什么。
设计 A 的整算要十几分钟，默认跳过：设 STEMLAB_SCIENCE_SLOW=1 才算；或者设 STEMLAB_SCIENCE_JOB 指向一个已经求解完的作业文件夹。
"""

# domain

实体只依赖标准库。乘客保留唯一对象与单向生命周期；接到时间为登梯完成，送达时间为离梯完成。Stop 保存具体乘客 ID，MotionSegment 为不可中途反转的相邻层运动。DecisionRequest 不可变且绑定唯一决策序号，避免过期动作重复生效。

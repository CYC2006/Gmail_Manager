"""
categories.py
Single source of truth for all AI email category strings and groupings.
Import from here instead of hardcoding strings across files.
"""

# Moodle categories
DEADLINE    = "作業死線"
HW_RELEASE  = "作業公布"
HW_CONFIRM  = "繳交確認"
GRADE       = "成績公布"
CANCEL      = "停課通知"
EXAM_RELATED = "考試相關"
EXAM_TIME   = "考試時間"

# General / school announcement categories
IMPORTANT   = "重要公告"
LECTURE     = "講座活動"
ANNOUNCE    = "一般宣導"
ADS         = "其他廣告"
EXTERNAL    = "外部學習"
OTHER       = "其他郵件"

# Categories that warrant auto-extracting a calendar event
CAL_WORTHY: frozenset[str] = frozenset({DEADLINE, CANCEL, EXAM_TIME})

# Categories eligible for preference keyword matching
MATCHABLE: frozenset[str] = frozenset({LECTURE, ANNOUNCE})

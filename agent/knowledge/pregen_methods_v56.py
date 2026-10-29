"""Reviewed predicates for the rc4.6 restricted pre-generation batch."""

PREGEN_METHODS_V56 = {
    'v9-public-toggle-divider-period': {
        'required': [
            r'\bdivide.by.four\b', r'\bsquare\s+wave\b',
            r'\bfirst\s+rises?\b[^.\n]{0,45}\bsecond\s+post.reset\s+edge\b',
            r'\bchanges?\s+every\s+two\s+edges\b', r'\bhold\s+no\s+extra\s+latency\b',
            r'\brising\s+clk\b',
        ],
        'known': [r'\bdivided\s*<=\s*~\s*divided\b[^.\n]{0,70}\b(?:phase|count)\b', r'\btoggle\s+interval\b[^.\n]{0,40}\btwo\s+edges\b'],
        'irrelevant': [r'\bchanges?\s+every\s+(?:one|four)\s+edges?\b', r'\boutput\s+period\b[^.\n]{0,35}\btwo\s+source\s+edges\b'],
    },
    'v9-public-fractional-period-duty': {
        'required': [
            r'\brising\s+clk\b', r'\breset\b[^.\n]{0,45}\b(?:wave\s+high|phase\s+zero)\b',
            r'\b1\s*,\s*0\s*,\s*0\s*,\s*0\s*,\s*1\b',
            r'\b(?:exact\s+five.cycle\s+alignment|not\s+just\s+the\s+two.fifths\s+duty)\b',
        ],
        'known': [r'\b(?:wave|output)\b\s*=\s*\(?\s*(?:phase|count)\b[^;\n]{0,45}\b(?:==|inside)\b'],
        'irrelevant': [r'\bphase\s+(?:alignment\s+)?(?:does\s+not|need\s+not)\s+matter\b', r'\bany\s+two.fifths\s+duty\b'],
    },
    'v9-public-hdlc-run-classification': {
        'required': [
            r'\bpreceding\s+ones\b', r'\bcurrent\s+zero\b',
            r'\bstuffed\b[^.\n]{0,35}\bfive\b', r'\bflag\b[^.\n]{0,35}\bsix\b',
            r'\babort\b[^.\n]{0,35}\bseven\s+or\s+more\b', r'\bcombinational\w*\b',
        ],
        'known': [r'\bones\s*==\s*5\b[^;\n]{0,90}\bones\s*==\s*6\b', r'\b5\s*:\s*stuffed\b[^.\n]{0,45}\b6\s*:\s*flag\b'],
        'irrelevant': [r'\bflag\b[^.\n]{0,25}\b(?:after|for)\s+five\b', r'\bfive\s+preceding\s+ones\b[^.\n]{0,30}\b(?:identify|mean)\w*\s+(?:a\s+)?flag\b', r'\babort\b[^.\n]{0,25}\b(?:after|for)\s+six\b'],
    },
    'v9-public-speculation-rollback-priority': {
        'required': [
            r'\bmispredict\b[^.\n]{0,45}\breplaces?\s+history\b',
            r'\brecovery_history\b', r'\bpriority\b[^.\n]{0,40}\bsame.edge\s+predict\b',
            r'\bpredict\s+alone\b[^.\n]{0,45}\bshift\s+history\s+left\b[^.\n]{0,35}\bappend\s+taken\b',
            r'\brising\s+clk\b',
        ],
        'known': [r'\bif\s*\(\s*mispredict\s*\)\b[^.\n]{0,70}\bhistory\s*<=\s*recovery_history\b'],
        'irrelevant': [r'\bpredict\b[^.\n]{0,35}\bpriority\b[^.\n]{0,35}\bmispredict\b', r'\bsame.edge\b[^.\n]{0,45}\bspeculative\s+update\b[^.\n]{0,35}\bafter\s+recovery\b'],
    },
    'v9-public-johnson-orbit': {
        'required': [
            r'\bfour.bit\s+state\b', r'\breset\b[^.\n]{0,35}\b0000\b', r'\bshift\s+right\b',
            r'\bcomplement\b[^.\n]{0,45}\bold\s+least\s+significant\s+bit\b',
            r'\beight.state\s+Johnson\s+orbit\b', r'\bwithout\s+binary\s+increment\b',
        ],
        'known': [r'\{\s*~\s*state\s*\[\s*0\s*\]\s*,\s*state\s*\[\s*3\s*:\s*1\s*\]\s*\}', r'\bcomplemented\s+LSB\b[^.\n]{0,35}\bMSB\b'],
        'irrelevant': [r'\bbinary\s+(?:count|increment)\b[^.\n]{0,35}\b(?:instead|required)\b', r'\bshift\s+left\b[^.\n]{0,45}\bcomplement\b'],
    },
    'v9-public-mixed-radix-time-rollover': {
        'required': [
            r'\bseconds\b[^.\n]{0,40}\bminutes\b', r'\bzero\s+through\s+59\b',
            r'\b59\s+seconds\b[^.\n]{0,45}\bwraps?\s+to\s+zero\b[^.\n]{0,45}\b(?:advances?|increments?)\s+minutes\b',
            r'\b59\s+minutes\b[^.\n]{0,45}\bwr(?:ap|app)\w*\s+to\s+zero\b', r'\bload\b[^.\n]{0,35}\bpriority\b',
        ],
        'known': [r'\bif\s*\(\s*sec\s*==\s*(?:6\'d)?59\s*\)', r'\bminutes?\b[^.\n]{0,45}\b(?:only\s+)?(?:advance|increment)\w*\b[^.\n]{0,35}\bseconds?\s+(?:wrap|rollover)\b'],
        'irrelevant': [r'\bseconds?\b[^.\n]{0,35}\bwraps?\b[^.\n]{0,35}\b(?:without|does\s+not)\s+(?:advance|increment)\w*\s+minutes?\b', r'\bmodulo\s+64\b'],
    },
    'v9-public-odd-divider-duty-limit': {
        'required': [
            r'\bdivide.by.three\b', r'\b1\s*,\s*0\s*,\s*0\b',
            r'\bone\s+high\b[^.\n]{0,40}\btwo\s+low\b', r'\bnot\s+an\s+equal.duty\s+square\s+wave\b',
            r'\brising\s+clk\b',
        ],
        'known': [r'\bphase\b[^.\n]{0,45}\b(?:three|3)\b[^.\n]{0,45}\b(?:high|divided)\b', r'\b(?:high|one)\b[^.\n]{0,35}\bphase\s+(?:zero|0)\b'],
        'irrelevant': [r'\b(?:generate|require|use)\w*\b[^.\n]{0,35}\b(?:exact|equal)\s+50\s*%\s+duty\b', r'\b(?:generate|require|use)\w*\b[^.\n]{0,35}\bequal.duty\s+square\s+wave\b'],
    },
    'v9-public-ring-onehot-invariant': {
        'required': [
            r'\bfour.bit\s+state\b', r'\breset\b[^.\n]{0,35}\b0001\b', r'\brotates?\s+it\s+left\b',
            r'\bwrap\w*\b[^.\n]{0,40}\bold\s+most\s+significant\s+bit\b[^.\n]{0,35}\bbit\s+zero\b',
            r'\bno\s+additional\s+illegal.state\s+recovery\b',
        ],
        'known': [r'\{\s*state\s*\[\s*2\s*:\s*0\s*\]\s*,\s*state\s*\[\s*3\s*\]\s*\}', r'\bone.hot\b[^.\n]{0,40}\brotate\b'],
        'irrelevant': [r'\bbinary\s+(?:count|increment)\b', r'\breset\b[^.\n]{0,35}\b0000\b'],
    },
    'v9-public-serial-error-rearm': {
        'required': [
            r'\bbad\s+stop\b|\bstop_ok\b', r'\brecovery\b[^.\n]{0,55}\bignores?\s+starts?\b',
            r'\bidle\s+high\b[^.\n]{0,55}\b(?:later|subsequent)\s+edge\b',
            r'\baccept\b[^.\n]{0,35}\berror\b[^.\n]{0,45}\bclear\w*\s+each\s+edge\b',
            r'\brising\s+clk\b',
        ],
        'known': [r'\bcase\s*\([^)]*state[^)]*\)[^.\n]{0,120}\brecovery\b[^.\n]{0,70}\bidle\b', r'\brearm\w*\s*<=\s*idle\b'],
        'irrelevant': [r'\brecovery\b[^.\n]{0,45}\baccept\w*\b[^.\n]{0,20}\bstarts?\b', r'\bbad\s+stop\b[^.\n]{0,45}\bimmediate\s+restart\b'],
    },
    'v9-public-signed-subtract-overflow': {
        'required': [
            r'\bsigned\b', r'\ba\s+minus\s+b\b', r'\blow\s+four\s+bits\b',
            r'\boverflow\b', r'\bminus\s+eight\s+through\s+seven\b', r'\bcombinational\w*\b',
        ],
        'known': [r'\boperand\s+signs?\s+differ\b[^.\n]{0,55}\bresult\s+sign\b[^.\n]{0,35}\bminuend\b', r'\(\s*a\s*\[\s*3\s*\]\s*\^\s*b\s*\[\s*3\s*\]\s*\)'],
        'irrelevant': [r'\bunsigned\s+(?:borrow|subtraction)\b', r'\bcarry.out\b[^.\n]{0,35}\boverflow\b'],
    },
}

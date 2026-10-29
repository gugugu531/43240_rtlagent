"""Bounded pre-generation predicates proposed for the second promotion batch."""

PREDICATES54 = {
    "v8-lfsr-feedback-seed": {
        "required": [
            r"\b(?:shift|shifting)\b[^.\n]{0,80}\b(?:state|bits?)\b|\bstate\s*\[",
            r"\b(?:xor|exclusive.or)\b[^.\n]{0,80}\b(?:tap|state|bit)\b|\bstate\s*\[\s*\d+\s*\]\s*\^",
            r"\b(?:reset|seed)\b[^.\n]{0,60}\b(?:nonzero|0*1|one)\b",
        ],
        "known": [r"\b(?:snapshot|state)\b[^.\n]{0,50}\b(?:xor|\^)\b[^.\n]{0,50}\b(?:nonzero\s+seed|seed\s+nonzero)\b"],
        "irrelevant": [r"\b(?:inverted.xor|xnor|complemented\s+feedback)\b", r"\breset\b[^.\n]{0,30}\b(?:all\s+zero|0{2,})\b"],
    },
    "v8-packer-valid-count": {
        "required": [
            r"\b(?:accept|accepted)\b[^.\n]{0,70}\b(?:valid|ready)\b",
            r"\b(?:pack|packing)\b[^.\n]{0,80}\b(?:items?|lanes?|word)\b",
            r"\b(?:bubbles?|unaccepted|not\s+accepted)\b[^.\n]{0,60}\b(?:do\s+not|does\s+not|holds?|not\s+advance)\b",
        ],
        "known": [r"\b(?:count|position|index)\b[^.\n]{0,60}\b(?:advance|increment)\w*\b[^.\n]{0,60}\b(?:valid\s*(?:&&|and)\s*ready|handshake|accepted)\b"],
        "irrelevant": [r"\b(?:every|each)\s+clock\b[^.\n]{0,40}\b(?:advance|increment)\b", r"\bignore\b[^.\n]{0,30}\bready\b"],
    },
    "v8-pipeline-valid-alignment": {
        "required": [
            r"\bstall\b[^.\n]{0,55}\b(?:holds?|retains?|freezes?)\b[^.\n]{0,45}\b(?:valid|result|both)\b|\b(?:valid|result|both)\b[^.\n]{0,45}\bstall\b[^.\n]{0,45}\bholds?",
            r"\b(?:out_valid|output\s+valid|valid)\b[^.\n]{0,55}\b(?:in_valid|input\s+valid)\b",
            r"\b(?:result|output)\b[^.\n]{0,70}\b(?:valid\s+input|in_valid|accepted)\b|\b(?:valid\s+input|in_valid)\b[^.\n]{0,70}\b(?:result|output)\b",
        ],
        "known": [r"\b(?:valid|result)\b[^.\n]{0,60}\b(?:same\s+(?:transaction|stall|enable)|together|aligned)\b"],
        "irrelevant": [r"\bvalid\b[^.\n]{0,50}\b(?:free.running|ignores?\s+stall|always\s+advance)\b"],
    },
    "v8-ram-port-write-mode": {
        "required": [
            r"\b(?:memory|ram)\b",
            r"\b(?:rising|clock|synchronous)\b",
            r"\b(?:same.address|read/write|read\s+and\s+write)\b[^.\n]{0,80}\b(?:old|pre.edge|read.first)\b|\b(?:old|pre.edge|read.first)\b[^.\n]{0,80}\b(?:same.address|read/write|read\s+and\s+write)\b",
        ],
        "known": [r"\bmem\s*\[[^\]]+\]\s*<=\s*[^;]+;[^.\n]{0,100}\b(?:q|dout|data_out)\s*<=\s*mem\s*\["],
        "irrelevant": [r"\b(?:write.first|new\s+data)\b", r"\bno.change\b"],
    },
    "v8-result-backpressure-retention": {
        "required": [
            r"\bvalid\b[^.\n]{0,50}\bhigh\b[^.\n]{0,50}\bready\b[^.\n]{0,30}\b(?:low|0)\b|\bready\b[^.\n]{0,30}\b(?:low|0)\b[^.\n]{0,50}\bvalid\b[^.\n]{0,30}\bhigh\b",
            r"\b(?:retain|hold|stable)\b[^.\n]{0,70}\b(?:valid|payload|value|result)\b",
            r"\b(?:produce|new\s+result)\b[^.\n]{0,70}\b(?:capture|valid|payload|value)\b",
        ],
        "known": [r"!\s*valid\w*\s*\|\|\s*ready|\bif\s*\(\s*(?:ready|!\s*valid)"],
        "irrelevant": [r"\b(?:drop|discard|overwrite)\b[^.\n]{0,55}\b(?:when|while|whenever)\b[^.\n]{0,35}\b(?:not\s+ready|ready\s+(?:is\s+)?(?:low|0))\b"],
    },
    "v8-serializer-snapshot": {
        "required": [
            r"\b(?:start|load|accept)\b[^.\n]{0,75}\b(?:word|data_in|parallel)\b",
            r"\b(?:bit\s*(?:zero|0)|least.significant|lsb)\b[^.\n]{0,70}\b(?:first|immediat\w*|emit\w*|output)\b|\b(?:first|immediat\w*|emit\w*|output)\b[^.\n]{0,70}\b(?:bit\s*(?:zero|0)|least.significant|lsb)\b",
            r"\b(?:later|live|subsequent)\b[^.\n]{0,45}\b(?:data(?:_in)?|input)\b[^.\n]{0,65}\b(?:do\s+not|does\s+not|must\s+not|not\s+affect)\b",
        ],
        "known": [r"\b(?:snapshot|shift\s+register)\b[^.\n]{0,55}\b(?:capture|load)\b[^.\n]{0,45}\bdata"],
        "irrelevant": [r"\b(?:live|current)\s+(?:parallel\s+)?input\b[^.\n]{0,60}\b(?:each|every)\s+(?:serialized\s+)?bit\b"],
    },
    "v8-stack-boundary-guards": {
        "required": [
            r"\bpush\b[^.\n]{0,55}\b(?:below\s+full|not\s+full|!\s*full|only)\b",
            r"\bpop\b[^.\n]{0,55}\b(?:nonempty|not\s+empty|!\s*empty|only)\b|\bnonempty\b[^.\n]{0,30}\bpop\b",
            r"\b(?:rejected|illegal|full\s+push|empty\s+pop)\b[^.\n]{0,60}\b(?:holds?|do\s+not|does\s+not|unchanged)\b",
        ],
        "known": [r"\bpush\b\s*(?:&&|and)\s*!\s*full|\bpop\b\s*(?:&&|and)\s*!\s*empty"],
        "irrelevant": [r"\b(?:overwrite|wrap)\b[^.\n]{0,45}\bfull\b", r"\bfull\b[^.\n]{0,45}\b(?:overwrite|wrap)\w*\b", r"\bpop\b[^.\n]{0,40}\bempty\b[^.\n]{0,30}\b(?:decrement|wrap)\b"],
    },
    "v9-public-am-pm-phase": {
        "required": [
            r"\b(?:eleven|11)\b[^.\n]{0,45}\b(?:twelve|12)\b[^.\n]{0,45}\b(?:flip\w*|toggl\w*|chang\w*)\b[^.\n]{0,30}\b(?:pm|am/pm|phase)\b",
            r"\b(?:twelve|12)\b[^.\n]{0,45}\b(?:one|1)\b[^.\n]{0,55}\b(?:without|do\s+not|does\s+not|no)\b[^.\n]{0,25}\b(?:flip\w*|toggl\w*|chang\w*)\b",
        ],
        "known": [r"\b(?:hour\s*==\s*(?:4'd)?11|hour\s+is\s+eleven)\b[^.\n]{0,90}\b(?:pm\s*<=\s*~\s*pm|toggle\s+pm)"],
        "irrelevant": [r"\b(?:twenty.four|24).hour\b", r"\b(?:twelve|12)\b[^.\n]{0,35}\b(?:one|1)\b[^.\n]{0,35}\b(?:flip|toggle)\b"],
    },
    "v9-public-carry-lookahead-composition": {
        "required": [
            r"\b(?:two|2)\s+carry\s+groups?\b|\bgroup\s*(?:zero|0)\b[^.\n]{0,80}\bgroup\s*(?:one|1)\b",
            r"\b(?:low.to.high|lower\s+group|group\s*(?:zero|0))\b[^.\n]{0,90}\b(?:carry|higher\s+group|group\s*(?:one|1))\b",
            r"\b(?:generate|g0|g1)\b[^.\n]{0,90}\b(?:propagate|p0|p1)\b",
        ],
        "known": [r"\bg1\b\s*\|[^;\n]*\bp1\b[^;\n]*\bg0\b[^;\n]*\bp0\b[^;\n]*\bcin\b"],
        "irrelevant": [r"\bindependent\s+groups?\b", r"\bcarry\s+groups?\b[^.\n]{0,35}\bindependent\b", r"\bhigher\s+group\b[^.\n]{0,45}\bcarry.in\b[^.\n]{0,20}\bzero\b"],
    },
    "v9-public-division-remainder-invariant": {
        "required": [
            r"\bunsigned\b",
            r"\bnonzero\s+divisor\b|\bdivisor\b[^.\n]{0,30}\bnonzero\b",
            r"\bdividend\b[^.\n]{0,30}\bquotient\b[^.\n]{0,30}\bdivisor\b[^.\n]{0,30}\bremainder\b",
            r"\bremainder\b[^.\n]{0,35}\b(?:less\s+than|<)\b[^.\n]{0,20}\bdivisor\b",
        ],
        "known": [r"\bquotient\b\s*=\s*\bdividend\b\s*/\s*\bdivisor\b[^;\n]*;[^.\n]{0,100}\bremainder\b\s*=\s*\bdividend\b\s*%\s*\bdivisor\b"],
        "irrelevant": [r"\bsigned\s+division\b", r"\bdivisor\b[^.\n]{0,30}\b(?:may\s+be|can\s+be|is)\s+zero\b"],
    },
}


IRRELEVANT54 = {
    "v8-lfsr-feedback-seed": "Use complemented XNOR feedback and reset all state bits to zero.",
    "v8-packer-valid-count": "Advance the position on every clock and ignore ready.",
    "v8-pipeline-valid-alignment": "Valid is free-running and ignores stall.",
    "v8-ram-port-write-mode": "The same-address operation is write-first and returns new data.",
    "v8-result-backpressure-retention": "Drop the pending result whenever ready is low.",
    "v8-serializer-snapshot": "Read the live parallel input again for every serialized bit.",
    "v8-stack-boundary-guards": "A push at full wraps and overwrites an entry.",
    "v9-public-am-pm-phase": "Use a twenty-four-hour counter.",
    "v9-public-carry-lookahead-composition": "The two carry groups are independent.",
    "v9-public-division-remainder-invariant": "Use signed division and allow divisor zero.",
}

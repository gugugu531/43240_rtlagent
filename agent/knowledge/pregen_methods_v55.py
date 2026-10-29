"""Reviewed public-specification predicates for the third restricted batch."""

_ALL_METHODS_V55 = {
    'v9-lang-comparison-result-sign': {
        'required': [
            r'\bunsigned\b[^.\n]{0,45}\binputs?\b|\binputs?\b[^.\n]{0,45}\bunsigned\b',
            r'\b(?:compare|smaller|less\s+than)\b',
            r'\bsigned\b[^.\n]{0,35}\b(?:result|output)\b|\b(?:result|output)\b[^.\n]{0,35}\bsigned\b',
            r'\b(?:positive\s+)?one\b[^.\n]{0,45}\bzero\b',
            r'\bcombinational\w*\b',
        ],
        'known': [r'\b(?:explicit|sized)\b[^.\n]{0,35}\b(?:positive\s+)?one\b[^.\n]{0,35}\bzero\b', r"\?\s*\d+'sd1\s*:\s*\d+'sd0"],
        'irrelevant': [r'\b(?:minus|negative)\s+one\b[^.\n]{0,35}\btrue\b', r'\btrue\b[^.\n]{0,35}\b(?:minus|negative)\s+one\b', r'\bone.bit\s+(?:result|output|destination)\b'],
    },
    'v9-lang-unsigned-negative-check': {
        'required': [
            r'\bunsigned\b', r'\b(?:minus|subtract\w*|difference)\b',
            r'\b(?:max\w*|clamp\w*|saturat\w*)\b[^.\n]{0,35}\bzero\b|\bzero\b[^.\n]{0,35}\b(?:max\w*|clamp\w*|saturat\w*)\b',
            r'\b(?:underflow|no\s+wraparound|without\s+wrap)\b', r'\bcombinational\w*\b',
        ],
        'known': [r'\bcompare\b[^.\n]{0,60}\b(?:operands|magnitudes|a\s+and\s+b)\b[^.\n]{0,40}\bbefore\b', r'\ba\s*<\s*b\s*\?'],
        'irrelevant': [r'(?<!no\s)(?<!without\s)\b(?:wrapping|modular|modulo)\s+subtraction\b', r'\bsigned\s+subtraction\b'],
    },
    'v9-public-sampled-edge-history': {
        'required': [
            r'\b(?:rising\s+clk|rising\s+clock|posedge)\b', r'\breset\b',
            r'\b(?:previous|prior|old)\s+sample\b', r'\b(?:low.to.high|0.to.1|rising\s+transition)\b',
            r'\b(?:sustained|steady)\s+(?:high|low)\b[^.\n]{0,45}\bzero\b|\bzero\b[^.\n]{0,45}\b(?:sustained|steady)\s+(?:high|low)\b',
            r'\bregistered\b',
        ],
        'known': [r'\b(?:current|signal_in)\b\s*&\s*~\s*(?:previous|prev|history)\b', r'\bstore\b[^.\n]{0,35}\bprevious\s+sample\b'],
        'irrelevant': [r'\b(?:falling|high.to.low)\s+(?:edge|event|transition)\b', r'\b(?:level|plateau)\b[^.\n]{0,35}\b(?:every|each)\s+cycle\b'],
    },
    'v9-lang-boolean-versus-bitwise': {
        'required': [r'\bmask\w*\b', r'\b(?:corresponding|each|per)[ -]?(?:output[ -])?bits?\b', r'\bbinary\b', r'\bcombinational\w*\b'],
        'known': [r'\bbitwise\s+(?:AND|conjunction)\b', r'\buse\b[^.\n]{0,35}\bsingle\s*&', r'\b\w+\s*=\s*\w+\s*&\s*\w+\s*;'],
        'irrelevant': [r'\b(?:one.bit|single.bit|scalar)\s+(?:truth|boolean)\b', r'\b(?:logical|Boolean)\s+reduction\b'],
    },
    'v9-public-triangle-endpoint-dwell': {
        'required': [
            r'\b0\s*,\s*0\s*,\s*1\s*,\s*2\s*,\s*2\s*,\s*1\b',
            r'\bendpoints?\b[^.\n]{0,45}\b(?:dwell|two\s+samples)\b',
            r'\b(?:synchronous|rising\s+clock|posedge)\b', r'\breset\b[^.\n]{0,45}\b(?:phase\s+zero|value\s+zero)\b',
        ],
        'known': [r'\b(?:state|phase)\b[^.\n]{0,60}\b0\s*,\s*0\s*,\s*1\s*,\s*2\s*,\s*2\s*,\s*1\b'],
        'irrelevant': [r'\brevers\w*\b[^.\n]{0,45}\bimmediately\b[^.\n]{0,35}\b(?:bound|endpoint)\b', r'\bno\s+(?:endpoint\s+)?dwell\b'],
    },
    'v9-public-grid-row-column-wrap': {
        'required': [
            r'\b(?:toroidal|wrap)\b', r'\brows?\b[^.\n]{0,45}\bcolumns?\b[^.\n]{0,35}\bindependent\w*\b',
            r'\b(?:three|3).row\b[^.\n]{0,35}\b(?:four|4).column\b', r'\bfour\s+orthogonal\b[^.\n]{0,35}\bneighbors?\b',
            r'\b0\s+through\s+11\b', r'\bcombinational\w*\b',
        ],
        'known': [r'\brow\b[^.\n]{0,35}\bmod(?:ulo)?\s*3\b[^.\n]{0,55}\bcolumn\b[^.\n]{0,35}\bmod(?:ulo)?\s*4\b'],
        'irrelevant': [r'\bflat.index\b[^.\n]{0,45}\bmodulo\b', r'\b(?:no|without)\s+(?:row|column)\s+wrap\b'],
    },
    'v8-pipeline-operand-cohort': {
        'required': [
            r'\bstall\b[^.\n]{0,60}\b(?:hold|retain|freeze)\w*\b[^.\n]{0,45}\b(?:sum|result|valid|both)\b',
            r'\b(?:same\s+(?:edge|transaction)|corresponding\s+(?:input|operands?))\b',
            r'\bvalid\s+input\b[^.\n]{0,65}\b(?:sum|result|capture)\w*\b|\b(?:sum|result)\b[^.\n]{0,65}\bvalid\s+input\b',
        ],
        'known': [r'\b(?:capture|register)\w*\b[^.\n]{0,55}\b(?:all|both)\s+operands?\b[^.\n]{0,35}\b(?:same|together)\b'],
        'irrelevant': [r'\b(?:mix|combine)\w*\b[^.\n]{0,55}\b(?:different|adjacent)\s+(?:cycles?|transactions?)\b', r'\boperands?\b[^.\n]{0,45}\bindependent\s+cycles?\b'],
    },
    'v9-lang-overlapping-case-order': {
        'required': [
            r'\b(?:exact|specific)\b[^.\n]{0,45}\b(?:case|101|value)\b',
            r'\b(?:broader|wildcard|high.bit)\b[^.\n]{0,55}\b(?:case|match|input)\b',
            r'\b(?:priority|first\s+match)\b',
            r'\bcombinational\w*\b',
        ],
        'known': [r'\b(?:put|place|write)\b[^.\n]{0,45}\b(?:specific|exact)\b[^.\n]{0,45}\b(?:before|first)\b', r'\bcasez\b[^.\n]{0,100}\bfirst\s+match\b'],
        'irrelevant': [r'\bmutually\s+exclusive\b', r'\bno\s+overlap\b', r'\bpriority\s+(?:does\s+not|must\s+not)\s+matter\b'],
    },
    'v9-public-cellular-snapshot-update': {
        'required': [
            r'\b(?:all|every)\s+cells?\b[^.\n]{0,65}\b(?:same|one)\s+(?:previous.state\s+)?snapshot\b|\ball\s+cells?\s+update\b[^.\n]{0,55}\bold\b',
            r'\b(?:neighbor|neighbour)\w*\b[^.\n]{0,55}\b(?:xor|exclusive.or)\b|\b(?:xor|exclusive.or)\b[^.\n]{0,55}\b(?:neighbor|neighbour)\w*\b',
            r'\b(?:wrap|periodic|ring)\b',
            r'\b(?:rising\s+clk|rising\s+clock|posedge)\b',
        ],
        'known': [r'\bnext.state\b[^.\n]{0,70}\b(?:from|using)\b[^.\n]{0,35}\b(?:old|previous|current)\s+state\b'],
        'irrelevant': [r'\bin.place\b[^.\n]{0,45}\bupdate\w*\b', r'\beach\s+cell\b[^.\n]{0,45}\b(?:new|updated)\s+neighbor\b'],
    },
    'v9-public-convolution-memory-depth': {
        'required': [
            r'\bcurrent\s+(?:input|bit_in|bit)\b[^.\n]{0,65}\bprevious\s+two\b|\bprevious\s+two\b[^.\n]{0,65}\bcurrent\b',
            r'\b(?:xor|exclusive.or)\b',
            r'\bhistory\b[^.\n]{0,60}\b(?:only\s+on|when)\s+valid\b|\bvalid\b[^.\n]{0,55}\badvance\w*\s+history\b',
        ],
        'known': [r'\bconstraint\s+length\b[^.\n]{0,45}\bincludes?\b[^.\n]{0,30}\bcurrent\s+input\b', r'\bhistory\b[^.\n]{0,35}\bK\s*-\s*1\b'],
        'irrelevant': [r'\bstore\w*\b[^.\n]{0,35}\bK\s+prior\s+bits\b', r'\binvalid\b[^.\n]{0,35}\badvance\w*\s+history\b'],
    },
    'v9-public-framing-search-phase': {
        'required': [
            r'\b(?:search|searching)\b[^.\n]{0,55}\b(?:0x7e|marker|start)\b',
            r'\bnext\s+two\b[^.\n]{0,45}\bpayload\b|\btwo\b[^.\n]{0,35}\bpayload\s+bytes?\b',
            r'\bpayload\b[^.\n]{0,65}\b(?:including|includes?|even)\b[^.\n]{0,35}\b0x7e\b',
            r'\bvalid\s+bytes?\b[^.\n]{0,45}\b(?:accepted|affect|framing)\b|\baccepted\s+valid\s+bytes?\b',
        ],
        'known': [r'\b(?:marker|0x7e)\b[^.\n]{0,60}\b(?:only|structural)\b[^.\n]{0,30}\bsearch\w*\b'],
        'irrelevant': [r'\b(?:escape|escaping|byte.stuff)\w*\b', r'\b0x7e\b[^.\n]{0,50}\b(?:always|inside\s+payload)\b[^.\n]{0,25}\b(?:restart|start\s+a\s+new)\b'],
    },
    'v9-public-instruction-bank-isolation': {
        'required': [
            r'\b(?:only|selected)\b[^.\n]{0,45}\bbank\b[^.\n]{0,55}\b(?:update|write|change)\w*\b|\bupdate\w*\b[^.\n]{0,45}\bonly\s+the\s+selected\s+bank\b',
            r'\b(?:other|unrelated)\b[^.\n]{0,35}\b(?:bank|location)\w*\b[^.\n]{0,45}\b(?:preserve|retain|hold)\w*\b',
            r'\b(?:bank|addr|address)\b',
            r'\b(?:rising\s+clk|rising\s+clock|posedge)\b',
        ],
        'known': [r'\bif\s*\(\s*(?:we|write_enable)\s*\)\b[^.\n]{0,90}\bbank\w*\s*\['],
        'irrelevant': [r'\b(?:broadcast|write\s+all)\b[^.\n]{0,45}\bbanks?\b', r'\bselected\s+write\b[^.\n]{0,45}\bclears?\s+(?:the\s+)?other\s+bank\b'],
    },
    'v9-public-pause-preserves-subtick': {
        'required': [
            r'\b(?:disabled|pause\w*)\b[^.\n]{0,55}\b(?:preserve|hold|retain)\w*\b[^.\n]{0,45}\b(?:phase|fractional|progress|count)\b',
            r'\b(?:every\s+fourth|four.step|4.step)\b[^.\n]{0,45}\b(?:enable|enabled|tick)\b',
            r'\b(?:resume|resumption)\b[^.\n]{0,45}\b(?:continue|partial|progress|count)\w*\b',
        ],
        'known': [r'\bif\s*\(\s*(?:enable|!\s*pause)\s*\)\b[^.\n]{0,100}\b(?:count|phase)\b'],
        'irrelevant': [r'\b(?:paus\w*|disabled)\b[^.\n]{0,45}\b(?:reset|clear)\w*\b[^.\n]{0,35}\b(?:phase|count|divider)\b', r'\bphase\b[^.\n]{0,35}\badvance\w*\b[^.\n]{0,35}\b(?:while\s+)?(?:paused|disabled)\b'],
    },
    'v9-lang-same-process-nba-order': {
        'required': [
            r'\bload\b[^.\n]{0,35}\bpriority\b|\bpriority\b[^.\n]{0,35}\bload\b',
            r'\binc\w*\b[^.\n]{0,45}\b(?:no|without)\s+load\b|\b(?:no|without)\s+load\b[^.\n]{0,45}\binc\w*\b',
            r'\bsimultaneous\b[^.\n]{0,55}\b(?:load|inc)\w*\b[^.\n]{0,45}\bload\s+value\b',
            r'\b(?:rising\s+clk|rising\s+clock|posedge)\b',
        ],
        'known': [r'\bif\s*\([^)]*load[^)]*\)\b[^.\n]{0,80}\belse\b[^.\n]{0,45}\binc', r'\blater\s+nonblocking\s+assignment\b[^.\n]{0,45}\bwins?\b'],
        'irrelevant': [r'\binc\w*\b[^.\n]{0,35}\bpriority\b[^.\n]{0,35}\bload\b', r'\bsimultaneous\b[^.\n]{0,45}\b(?:increment|inc)\s+value\b'],
    },
}


_SELECTED_V55 = {
    'v9-public-cellular-snapshot-update',
    'v9-public-triangle-endpoint-dwell',
    'v9-public-grid-row-column-wrap',
    'v9-lang-comparison-result-sign',
    'v9-lang-unsigned-negative-check',
    'v9-public-sampled-edge-history',
    'v9-public-framing-search-phase',
    'v9-public-instruction-bank-isolation',
    'v9-public-pause-preserves-subtick',
    'v9-lang-boolean-versus-bitwise',
}
PREGEN_METHODS_V55 = {key: _ALL_METHODS_V55[key] for key in _SELECTED_V55}

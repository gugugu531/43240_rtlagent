"""Bounded next-cohort specification methods; publication state gates sending."""
import re

METHODS = {
    'v9-lang-boolean-versus-bitwise': {
        'required': [r'\bmask\w*\b', r'\b(?:corresponding|each|per)[ -]?(?:output[ -])?bits?\b', r'\bbinary\b', r'\bcombinational\b'],
        'known': [r'\bbitwise\s+(?:AND|conjunction)\b', r'\buse\b[^.\n]{0,35}\bsingle\s*&', r'\b\w+\s*=\s*\w+\s*&\s*\w+\s*;'],
        'irrelevant': [r'\b(?:one.bit|single.bit|scalar)\s+(?:truth|boolean)\b', r'\b(?:logical|Boolean)\s+reduction\b'],
    },
    'v9-lang-unsigned-negative-check': {
        'required': [r'\bunsigned\b', r'\b(?:subtract\w*|difference)\b', r'\b(?:clamp\w*|saturat\w*)\b', r'\bzero\b', r'\bbinary\b', r'\bcombinational\b'],
        'known': [r'\bcompare\b[^.\n]{0,60}\b(?:operands|magnitudes)\b[^.\n]{0,40}\bbefore\b', r'\b(?:left|a)\s*<\s*(?:right|b)\s*\?', r'\b(?:widened|explicit)\s+borrow\b'],
        'irrelevant': [r'\b(?:signed\s+subtraction|signed\s+operands|modular\s+subtraction)\b', r'\b(?:wrap\w*|modulo)\b'],
    },
    'v9-public-sampled-edge-history': {
        'required': [r'\b(?:rising event|low.to.high|0.to.1)\b', r'\b(?:sample\w*|synchronous)\b', r'\b(?:rising clock|posedge)\b', r'\breset\b', r'\bhistory\b[^.\n]{0,35}\b(?:zero|0)\b', r'\bbinary\b'],
        'known': [r'\b(?:previous|old)\s+sample\b[^.\n]{0,35}\b(?:low|zero)\b[^.\n]{0,35}\bcurrent\b', r'\b\w+\s*&\s*~\s*(?:previous|history|prev)\b', r'\bstore\b[^.\n]{0,30}\bprevious\s+sample\b'],
        'irrelevant': [r'\basynchronous\b', r'\b(?:falling|high.to.low)\s+(?:event|transition)\b', r'\b(?:level.only|every high sample)\b'],
    },
    'v9-public-bounded-modulus': {
        'required': [r'\bcounter\b', r'\b0\s+through\s+\d+\b', r'\b(?:wrap\w*|modulo)\b', r'\b(?:enable|advance)\b', r'\b(?:rising clock|posedge)\b', r'\breset\b[^.\n]{0,35}\b(?:zero|0)\b'],
        'known': [r'\bcompare\b[^.\n]{0,45}\b(?:terminal|maximum)\b', r'\buse\b[^.\n]{0,30}\bmodulo operator\b', r'\b(?:count|q)\s*==\s*\d+\s*\?'],
        'irrelevant': [r'\b(?:saturat\w*|clamp\w*)\b', r'\bdown.counter\b'],
    },
    'v9-public-saturation-not-wrap': {
        'required': [r'\bunsigned\b', r'\bcounter\b', r'\b(?:saturat\w*|clamp\w*)\b', r'\b\d+\s+through\s+\d+\b', r'\bup\b', r'\bdown\b', r'\b(?:rising clock|posedge)\b', r'\breset\b', r'\bnever\s+simultaneously\b'],
        'known': [r'\bguard\b[^.\n]{0,40}\b(?:increment|decrement|endpoint)\b', r'\bcompare\b[^.\n]{0,45}\b(?:minimum|maximum|endpoints)\b'],
        'irrelevant': [r'\b(?:wrapping|modulo)\s+counter\b', r'\bsigned\s+counter\b'],
    },
    'v8-packer-temporal-order': {
        'required': [r'\btwo.item\b', r'\bpack\w*\b', r'\baccept\w*\b', r'\bfirst\b[^.\n]{0,45}\blow\b', r'\bsecond\b[^.\n]{0,45}\bhigh\b', r'\b(?:rising clock|posedge)\b', r'\breset\b', r'\bbinary\b'],
        'known': [r'\b(?:save|store|register)\b[^.\n]{0,35}\bfirst accepted\b', r'\{\s*(?:item|second)\s*,\s*(?:first_item|saved_first)\s*\}'],
        'irrelevant': [r'\b(?:combinational|three.item)\b', r'\bfirst\b(?:(?!\bsecond\b)[^.\n]){0,35}\bhigh\b'],
    },
}
METHODS.update({
    'v9-lang-comparison-result-sign': {
        'required': [r'\bunsigned\b', r'\bcompar\w*\b', r'\bsigned\b', r'\b(?:one|1)\b[^.\n]{0,35}\btrue\b|\btrue\b[^.\n]{0,35}\b(?:one|1)\b', r'\b(?:zero|0)\b[^.\n]{0,35}\bfalse\b|\bfalse\b[^.\n]{0,35}\b(?:zero|0)\b', r'\bcombinational\b', r'\bbinary\b'],
        'known': [r'\b(?:explicit|sized)\b[^.\n]{0,35}\b(?:true|numeric)\s+codes?\b', r"\?\s*\d+'sd1\s*:\s*\d+'sd0", r'\bunsigned\s+one.bit\s+(?:predicate|comparison result)\b'],
        'irrelevant': [r'\b(?:minus one|negative one|-1)\b[^.\n]{0,30}\btrue\b', r'\btrue\b[^.\n]{0,30}\b(?:minus one|negative one|-1)\b'],
    },
    'v9-public-block-carry-chain': {
        'required': [r'\bunsigned\b', r'\b(?:add\w*|sum)\b', r'\b(?:two|2)\b[^.\n]{0,30}\bblocks?\b', r'\b(?:low|lower)\b', r'\b(?:high|upper)\b', r'\bcarry\b', r'\b(?:exact|full)\b', r'\bcombinational\b', r'\bbinary\b'],
        'known': [r'\b(?:connect|feed|propagate)\b[^.\n]{0,45}\b(?:lower|low)\b[^.\n]{0,40}\bcarry\b[^.\n]{0,40}\b(?:upper|high)\b', r'\binter.block\s+carry\s+(?:is\s+)?(?:connected|complete)\b'],
        'irrelevant': [
            r'\bindependent\s+(?:lanes|blocks)\b',
            r'\bdiscard\b[^.\n]{0,35}\bcarry\b',
            r'\b(?:no|without)\s+inter[ -]?block\s+carry\b',
            r'\b(?:upper|high)\s+(?:block\s+)?carry[ -]?in\s+(?:is\s+)?(?:zero|0)\b',
        ],
    },
    'v9-public-batch-final-sample': {
        'required': [r'\b(?:batch|group)\b', r'\b(?:sum|accumulat\w*)\b', r'\baccepted\b', r'\b(?:non.overlapping|disjoint)\b', r'\b(?:rising clock|posedge)\b', r'\b(?:last|final|completion)\b[^.\n]{0,50}\b(?:edge|acceptance|sample)\b', r'\breset\b', r'\bunsigned\b', r'\bbinary\b'],
        'known': [r'\binclude\b[^.\n]{0,25}\b(?:terminal|final|last)\s+sample\b[^.\n]{0,35}\b(?:publication|expression)\b', r'\b(?:sum|accumulator)\s*\+\s*(?:sample|item)\b', r'\bpublish\b[^.\n]{0,35}\b(?:sum|accumulator)\s*plus\s*(?:sample|item)\b'],
        'irrelevant': [
            r'\b(?:sliding|running)\s+(?:window|sum)\b',
            r'(?<!non-)(?<!non )\boverlapping\s+(?:groups|batches)\b',
            r'\b(?:exclude|omit|ignore)\b[^.\n]{0,40}\b(?:last|final|completion)\s+sample\b',
            r'\bpublish\b[^.\n]{0,45}\b(?:old|previous|pre[ -]?edge)\s+(?:sum|accumulator)\b',
        ],
    },
})


def contract_guard(card_id, prompt, interface):
    """Return a refusal only for extra structural bounds beyond lexical terms."""
    if card_id not in METHODS:
        return None
    output_widths = [abs(int(a)-int(b))+1 for a,b in re.findall(
        r'\boutput\b\s*(?:(?:wire|reg|logic|signed|unsigned)\b\s*)*\[(\d+)\s*:\s*(\d+)\]', interface)]
    width_bounded = {
        'v9-lang-boolean-versus-bitwise', 'v9-lang-unsigned-negative-check',
        'v9-lang-comparison-result-sign', 'v8-packer-temporal-order',
        'v9-public-bounded-modulus', 'v9-public-saturation-not-wrap',
    }
    if card_id in width_bounded and not output_widths:
        return ('unknown', 'explicit_output_width_missing')
    if card_id in ('v9-lang-boolean-versus-bitwise', 'v9-lang-unsigned-negative-check') and max(output_widths)<2:
        return ('not_needed', 'multibit_method_not_applicable')
    if card_id=='v9-lang-comparison-result-sign' and max(output_widths)<2:
        return ('not_needed','one_bit_truth_destination')
    if card_id=='v8-packer-temporal-order':
        # A lane-order topic alone does not establish publication or reset timing.
        if not re.search(r'\bsynchronous\b',prompt,re.I) or not re.search(r'\breset\b[^.\n]{0,70}\bclear\w*\b',prompt,re.I):
            return ('unknown','packer_reset_contract_missing')
        if not re.search(r'\bactive[ -]high\b[^.\n]{0,20}\breset\b|\breset\b[^.\n]{0,20}\bactive[ -]high\b',prompt,re.I) or re.search(r'\b(?:asynchronous|active[ -]low)\b',prompt,re.I):
            return ('unknown','packer_reset_polarity_not_bound')
        if re.search(r'\b(?:do not|must not|never)\s+(?:publish|produce|update|emit)\b',prompt,re.I):
            return ('unknown','packer_publication_conflict')
        publication=re.search(r'\b(?:publish|produce|update|emit)\b[^.\n]{0,45}\b(?:on|at)\s+(?:the\s+)?second\s+(?:acceptance|accepted\s+(?:item|input|sample)(?:\s+(?:edge|event))?)\b',prompt,re.I)
        if not publication:
            return ('unknown','packer_publication_edge_missing')
        if re.search(r'\b(?:next|following|third|later|delay\w*)\b[^.\n]{0,25}\b(?:clock|edge|cycle|acceptance|publish\w*)\b',prompt,re.I):
            return ('unknown','packer_publication_conflict')
        if not re.search(r'\b(?:one|single|1).cycle\b[^.\n]{0,30}\b(?:[A-Za-z_]\w*_)?valid\b|\b(?:[A-Za-z_]\w*_)?valid\b[^.\n]{0,35}\b(?:one|single|1)\s+cycle\b',prompt,re.I):
            return ('unknown','packer_valid_contract_missing')
        if not re.search(r'\b(?:retain|hold)\w*\b',prompt,re.I):
            return ('unknown','packer_output_retention_missing')
        from agent.rtl.task import TaskSpec
        try:ports=TaskSpec.from_text('packer-interface',prompt,interface).expected_interface.ports
        except (ValueError,AttributeError):return ('unknown','packer_interface_not_resolved')
        inputs=[p.width for p in ports if p.direction=='input' and p.width and p.width>1]
        outputs=[p.width for p in ports if p.direction=='output' and p.width and p.width>1]
        if len(inputs)!=1 or len(outputs)!=1 or outputs[0]!=2*inputs[0]:
            return ('unknown','packer_lane_widths_not_bound')
    if card_id in ('v9-public-bounded-modulus', 'v9-public-saturation-not-wrap'):
        match=re.search(r'\b(\d+)\s+through\s+(\d+)\b',prompt,re.I)
        if not match:
            return ('unknown','numeric_counter_limits_missing')
        lo,hi=map(int,match.groups());width=max(output_widths)
        if width>32 or not 0<=lo<hi<(1<<width):
            return ('unknown','counter_limits_not_representable')
        if card_id=='v9-public-bounded-modulus' and (lo!=0 or hi==(1<<width)-1):
            return ('not_needed','full_binary_modulus_or_nonzero_origin')
    return None

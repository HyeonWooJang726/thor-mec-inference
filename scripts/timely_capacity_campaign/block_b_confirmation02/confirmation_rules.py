"""Pre-registered C1-C5 arithmetic; no hardware/runtime dependencies."""

ETA = 0.99
CELLS = ((216, 'A'), (200, 'A'), (200, 'S'), (208, 'S'), (192, 'S'))


def decide(results):
    by = {}
    for row in results:
        key = (int(row['round']), int(row['rate_local']), row['pattern'][0])
        if key in by:
            raise ValueError('Duplicate confirmation cell/round')
        by[key] = row
    expected = {(round_, rate, token) for round_ in range(1, 6) for rate, token in CELLS}
    if set(by) != expected:
        raise ValueError('Confirmation result grid is incomplete or outside frozen cells')
    c1=[];c2=[];c3=[];c4=[];c5=[];rounds=[]
    for round_ in range(1,6):
        a216=by[round_,216,'A'];a200=by[round_,200,'A']
        s200=by[round_,200,'S'];s208=by[round_,208,'S'];s192=by[round_,192,'S']
        feasible200=s200['worst_stream_TIR']>=ETA
        feasible208=s208['worst_stream_TIR']>=ETA
        feasible192=s192['worst_stream_TIR']>=ETA
        temporal=(s200['total_timely_FPS']>a200['total_timely_FPS'] and
                  s200['worst_stream_TIR']>=a200['worst_stream_TIR'])
        aggressive=(s200['total_timely_FPS']>a216['total_timely_FPS'] and
                    s200['worst_stream_TIR']>=a216['worst_stream_TIR'])
        c1.append({'round':round_,'L200S_worst_stream_TIR':s200['worst_stream_TIR'],
                   'eta':ETA,'passes':feasible200})
        c2.append({'round':round_,'L200S_minus_L200A_timely_FPS':s200['total_timely_FPS']-a200['total_timely_FPS'],
                   'L200S_minus_L200A_worst_stream_TIR':s200['worst_stream_TIR']-a200['worst_stream_TIR'],
                   'strict_timely_and_nonstrict_worst_pass':temporal})
        c3.append({'round':round_,'L200S_minus_L216A_timely_FPS':s200['total_timely_FPS']-a216['total_timely_FPS'],
                   'L200S_minus_L216A_worst_stream_TIR':s200['worst_stream_TIR']-a216['worst_stream_TIR'],
                   'strict_timely_and_nonstrict_worst_pass':aggressive})
        c4.append({'round':round_,'L208S_worst_stream_TIR':s208['worst_stream_TIR'],
                   'eta':ETA,'passes':feasible208})
        c5.append({'round':round_,'L192S_worst_stream_TIR':s192['worst_stream_TIR'],
                   'eta':ETA,'passes':feasible192})
        rounds.append({'round':round_,**{f'L{rate}{token}_timely_FPS':by[round_,rate,token]['total_timely_FPS']
                                       for rate,token in CELLS},
                       **{f'L{rate}{token}_worst_stream_TIR':by[round_,rate,token]['worst_stream_TIR']
                          for rate,token in CELLS},
                       'C1_pass':feasible200,'C2_pass':temporal,'C3_pass':aggressive,
                       'L208S_feasible':feasible208,'L192S_feasible':feasible192})
    all1=all(r['passes'] for r in c1)
    all4=all(r['passes'] for r in c4)
    all5=all(r['passes'] for r in c5)
    summary={
        'C1':'L200S_FEASIBILITY_CONFIRMED' if all1 else 'L200S_FEASIBILITY_NOT_CONFIRMED',
        'C2':'L200_TEMPORAL_EFFECT_CONFIRMED' if all(r['strict_timely_and_nonstrict_worst_pass'] for r in c2)
             else 'L200_TEMPORAL_EFFECT_NOT_CONFIRMED',
        'C3':'L200S_VS_L216A_CONFIRMED' if all(r['strict_timely_and_nonstrict_worst_pass'] for r in c3)
             else 'L200S_VS_L216A_NOT_CONFIRMED',
        'C4':'MAX_LOCAL_SELECTION_NOT_CONFIRMED' if all4 else 'MAX_LOCAL_SELECTION_CONSISTENT',
        'C5':'BOTH_L200S_AND_L192S_FEASIBLE_DESCRIPTIVE' if all1 and all5 else
             'BOTH_FEASIBLE_NOT_OBSERVED',
        'eta':ETA,'L208S_feasible_run_count':sum(r['passes'] for r in c4),
        'L192S_feasible_run_count':sum(r['passes'] for r in c5),
        'C5_Edge_assigned_FPS_if_both_feasible':{'L200S':40,'L192S':48} if all1 and all5 else None,
        'no_statistical_significance_claim':True,
        'mu_backlog_lower_not_used':True,
    }
    return summary, rounds, {'C1_feasibility.csv':c1,'C2_L200_temporal_effect.csv':c2,
        'C3_L200S_vs_L216A.csv':c3,'C4_max_local_check.csv':c4,'C5_L192_sensitivity.csv':c5}

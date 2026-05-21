#!/bin/env python3.12

#-------------------------------------------------------
    
def split_to_list(_in: str) -> list:
    ''' split a string into a list of strings, splitting on spaces and commas '''
    #print(f"pal_comp: split input: {_in}");
    out = []
    if _in is None: return []
    # first split on spaces
    no_spaces = str(_in).split(" ")
    # then split any commas, adding to the end of the list
    for list_item in no_spaces:
        no_commas = list_item.split(",")
        # we might have split one of the indicies into two, append them both
        for x in no_commas:
            if x != "":
                out.append(x)
    #print(f"pal_comp: split output: {out}");
    return out

import re

existing_arcs = ['"Marvel Multiverse" Marvel Zombies', '"Marvel Multiverse" Marvel Zombies', 'Marvel Multiverse" Marvel Zombies']
existing_nums = ['1', '1', '1', '1']

clean_arcs = []
clean_nums = []
seen_arcs = set()
for a, n in zip(existing_arcs, existing_nums):
    norm_a = re.sub(r'["\'\(\):]', " ", a).lower().strip()
    norm_a = " ".join(norm_a.split())
    if norm_a and norm_a not in seen_arcs:
        seen_arcs.add(norm_a)
        clean_arcs.append(a.strip().strip('"').strip("'"))
        clean_nums.append(n.strip())

print("Clean Arcs:", clean_arcs)
print("Clean Nums:", clean_nums)

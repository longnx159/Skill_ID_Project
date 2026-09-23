"""
Production Script: Semi Stone Composition Scoring Model
Generates: Semi_Stone_Composition_Scoring_Model.xlsx in target directory
Grain: 1 row = 1 SemiBOM
"""

import os
import shutil
import re
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule

def main():
    print("=== STARTING STONE COMPLEXITY SCORING MODEL GENERATION ===")
    
    work_dir = r"d:\Manufacturing Data Analysis\Skill ID project\Stone"
    paths_file = os.path.join(work_dir, 'semi_stone_paths.csv')
    master_file = os.path.join(work_dir, 'stone_master_check.csv')
    item_file = os.path.join(work_dir, '02d50329-8160-4243-93e5-f6bd752e937c.xlsx')
    output_file = os.path.join(work_dir, 'Semi_Stone_Composition_Scoring_Model.xlsx')
    
    # 1. Load Data
    print(f"Loading input files from: {work_dir}")
    df_paths = pd.read_csv(paths_file)
    df_master = pd.read_csv(master_file)
    df_item = pd.read_excel(item_file)
    print(f"Loaded paths rows: {len(df_paths)}, master rows: {len(df_master)}, item rows: {len(df_item)}")
    
    # 2. Composition Validation Across FGs
    comp_per_fg = df_paths.groupby(['SemiBOM', 'FG BOM', 'StoneSKU'])['EffectiveStoneCount'].sum().reset_index()
    def make_comp_tuple(sub_df):
        sub_sorted = sub_df.sort_values('StoneSKU')
        return tuple(zip(sub_sorted['StoneSKU'], sub_sorted['EffectiveStoneCount']))

    semi_fg_comps = comp_per_fg.groupby(['SemiBOM', 'FG BOM']).apply(make_comp_tuple).reset_index(name='comp_tuple')
    comp_variance = semi_fg_comps.groupby('SemiBOM')['comp_tuple'].nunique()
    conflicts = comp_variance[comp_variance > 1]
    num_conflicts = len(conflicts)
    print(f"Composition conflicts across FGs: {num_conflicts}")
    if num_conflicts > 0:
        print("WARNING: Conflicting compositions detected in Semis:", conflicts.index.tolist())
    
    # FG Use Count per Semi
    fg_use_counts = df_paths.groupby('SemiBOM')['FG BOM'].nunique().to_dict()
    
    # Representative FG BOM: pick the first FG BOM encountered
    rep_fg_boms = df_paths.groupby('SemiBOM')['FG BOM'].first().to_dict()
    
    # Filter paths for the representative FG BOM for each Semi
    df_rep = df_paths[df_paths.apply(lambda r: r['FG BOM'] == rep_fg_boms[r['SemiBOM']], axis=1)]
    
    # Aggregate within (SemiBOM, StoneSKU) summing EffectiveStoneCount
    semi_stone_agg = df_rep.groupby(['SemiBOM', 'StoneSKU'])['EffectiveStoneCount'].sum().reset_index()
    print(f"Total aggregated detail rows (SemiBOM + StoneSKU): {len(semi_stone_agg)}")
    print(f"Total unique SemiBOMs: {semi_stone_agg['SemiBOM'].nunique()}")
    
    # 3. Build Stone Master Lookup and Parsing
    master_lookup = df_master.set_index('Component item number').to_dict(orient='index')
    item_lookup = df_item.set_index('Item number').to_dict(orient='index')
    
    def parse_stone(sku):
        m_info = master_lookup.get(sku, {})
        i_info = item_lookup.get(sku, {})
        
        pname = str(i_info.get('Product name', ''))
        stype = str(m_info.get('StoneType', ''))
        known_weight_g = m_info.get('KnownUnitWeightGram', np.nan)
        if pd.isna(known_weight_g):
            known_weight_g = None
        else:
            known_weight_g = float(known_weight_g)
            
        unit_weight_ct = (known_weight_g * 5.0) if known_weight_g is not None else None
        
        # Pearl Detection: ShapeFamily = "Pearl" if StoneType == "Pearl" OR "pearl" in Product name
        is_pearl = (stype == "Pearl") or bool(re.search(r'\bpearl\b', pname, re.IGNORECASE))
        pearl_mismatch = is_pearl and (stype != "Pearl")
        
        # Cut Profile Parsing
        pname_lower = pname.lower()
        cut_candidates = [
            ("Brilliant", r'\bbrilliant\b|\bbrill\b'),
            ("Cabochon", r'\bcabochon\b|\bcab\b'),
            ("Rose Cut", r'\brose\s*cut\b|\brose\b'),
            ("Briolette", r'\bbriolette\b'),
            ("Step Cut", r'\bstep\s*cut\b'),
            ("Faceted", r'\bfaceted\b|\bfacet\b')
        ]
        found_cuts = []
        for c_name, c_pat in cut_candidates:
            m = re.search(c_pat, pname_lower)
            if m:
                found_cuts.append((m.start(), c_name))
        found_cuts.sort(key=lambda x: x[0])
        cut_profile = "; ".join([c[1] for c in found_cuts]) if found_cuts else None
        
        # Pearl Drill Type Parsing
        drill_type = None
        if re.search(r'\bhalf\s*drill\b|\bhalf\s*dril\b|\bhalf\s*hole\b', pname_lower):
            drill_type = "Half Drill"
        elif re.search(r'\btop\s*drill\b', pname_lower):
            drill_type = "Top Drill"
        elif re.search(r'\bfull\s*drill\b|\bfull\s*drilll\b', pname_lower):
            drill_type = "Full Drill"
        elif re.search(r'\bcenter\s*drill\b', pname_lower):
            drill_type = "Center Drill"
        elif re.search(r'\bno\s*drill\b', pname_lower):
            drill_type = "No Drill"
            
        # Shape Parsing
        shape_source = "Explicit"
        if is_pearl:
            shape_family = "Pearl"
            if re.search(r'\bbaroque\b', pname_lower):
                stone_shape = "Baroque"
            elif re.search(r'\bpotato\b', pname_lower):
                stone_shape = "Potato"
            elif re.search(r'\brice\b', pname_lower):
                stone_shape = "Rice"
            elif re.search(r'\bbutton\b', pname_lower):
                stone_shape = "Button"
            elif re.search(r'\bnear\s*round\b|\bsemi\s*round\b', pname_lower):
                stone_shape = "Near Round"
            elif re.search(r'\boval\b', pname_lower):
                stone_shape = "Oval"
            elif re.search(r'\bdrop\b', pname_lower):
                stone_shape = "Drop"
            elif re.search(r'\bcoin\b|\bufo\b|\bmabe\b', pname_lower):
                stone_shape = "Coin / UFO / Mabe"
            elif re.search(r'\bround\b', pname_lower):
                stone_shape = "Round"
            else:
                stone_shape = "Round"
                shape_source = "Default"
        else:
            shape_family = "Gemstone"
            is_emerald_cut = bool(re.search(r'\bemerald\s+cut\b', pname_lower))
            if re.search(r'\bmaquire\b', pname_lower):
                stone_shape = "Marquise"
                shape_source = "Corrected"
            elif is_emerald_cut:
                stone_shape = "Emerald Cut"
            elif re.search(r'\bheart\b', pname_lower):
                stone_shape = "Heart"
            elif re.search(r'\bstar\b', pname_lower):
                stone_shape = "Star"
            elif re.search(r'\bmarquise\b', pname_lower):
                stone_shape = "Marquise"
            elif re.search(r'\btrillion\b|\btrilliant\b', pname_lower):
                stone_shape = "Trillion"
            elif re.search(r'\bprincess\b', pname_lower):
                stone_shape = "Princess"
            elif re.search(r'\bpear\b', pname_lower):
                stone_shape = "Pear"
            elif re.search(r'\bdrop\b', pname_lower):
                stone_shape = "Drop"
            elif re.search(r'\begg\b', pname_lower):
                stone_shape = "Egg"
            elif re.search(r'\bonion\b', pname_lower):
                stone_shape = "Onion"
            elif re.search(r'\bbaguette\b', pname_lower):
                stone_shape = "Baguette"
            elif re.search(r'\brectangle\b|\brectangular\b|\boctagon\b|\bsquare\b', pname_lower):
                stone_shape = "Rectangle"
            elif re.search(r'\bcushion\b', pname_lower):
                stone_shape = "Cushion"
            elif re.search(r'\boval\b', pname_lower):
                stone_shape = "Oval"
            elif re.search(r'\bround\b|\brd\b', pname_lower):
                stone_shape = "Round"
            else:
                stone_shape = "Round"
                shape_source = "Default"
                
        # Size Extraction (avoiding drill dimensions)
        drill_cleaned = pname
        num_pat = r'\d+(?:[.,]\d+)?'
        drill_patterns = [
            rf'(?:top|half|full|center)\s*(?:drill|drilll|hole)\s*(?:{num_pat}\s*[xX*]\s*{num_pat}(?:\s*mm)?)',
            rf'\((?:top|half|full|center)\s*(?:drill|drilll|hole)\)\s*(?:{num_pat}\s*[xX*]\s*{num_pat}(?:\s*mm)?)',
            rf'(?:{num_pat}\s*[xX*]\s*{num_pat}\s*mm?)\s*hole',
            rf'(?:top|half|full|center)\s*drill\s*(?:{num_pat}\s*[xX*]\s*{num_pat})?'
        ]
        for pat in drill_patterns:
            drill_cleaned = re.sub(pat, ' [DRILL_REMOVED] ', drill_cleaned, flags=re.IGNORECASE)
            
        num_or_range = r'\d+(?:[.,]\d+)?(?:\s*-\s*\d+(?:[.,]\d+)?)?'
        dim_pat = rf'({num_or_range}(?:\s*[xX*]\s*{num_or_range})*)\s*(?:mm|m\b)'
        matches = list(re.finditer(dim_pat, drill_cleaned, re.IGNORECASE))
        
        candidates = []
        for m in matches:
            raw = m.group(0).strip()
            dim_part = m.group(1).strip()
            start_idx = m.start()
            prefix = drill_cleaned[max(0, start_idx-15):start_idx].lower()
            is_height_or_thick = ('h=' in prefix or 'hi=' in prefix or 'h ' in prefix or 'thickness' in prefix)
            vals = []
            for part in re.split(r'[xX*]', dim_part):
                n_list = [float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', part)]
                if n_list:
                    vals.append(max(n_list))
            if vals:
                candidates.append({
                    'raw': raw,
                    'dim_part': dim_part,
                    'max_val': max(vals),
                    'is_secondary': is_height_or_thick,
                    'num_dims': len(vals)
                })
                
        if not candidates:
            no_mm_pat = rf'\b({num_or_range}(?:\s*[xX*]\s*{num_or_range})+)\b'
            matches2 = list(re.finditer(no_mm_pat, drill_cleaned))
            for m in matches2:
                raw = m.group(0).strip()
                dim_part = m.group(1).strip()
                vals = []
                for part in re.split(r'[xX*]', dim_part):
                    n_list = [float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', part)]
                    if n_list:
                        vals.append(max(n_list))
                if vals:
                    candidates.append({
                        'raw': raw,
                        'dim_part': dim_part,
                        'max_val': max(vals),
                        'is_secondary': False,
                        'num_dims': len(vals)
                    })
                    
        if not candidates:
            trunc_m = re.search(r'(\d+(?:[.,]\d+)?)\s*x\s*$', drill_cleaned.strip(), re.IGNORECASE)
            if trunc_m:
                v = float(trunc_m.group(1).replace(',', '.'))
                candidates.append({'raw': trunc_m.group(0).strip(), 'dim_part': str(v), 'max_val': v, 'is_secondary': False, 'num_dims': 1})
            else:
                trunc_m2 = re.search(r'(\d+(?:[.,]\d+)?)\s*-\s*(\d+)?\.?$', drill_cleaned.strip(), re.IGNORECASE)
                if trunc_m2:
                    v = float(trunc_m2.group(1).replace(',', '.'))
                    candidates.append({'raw': trunc_m2.group(0).strip(), 'dim_part': str(v), 'max_val': v, 'is_secondary': False, 'num_dims': 1})
                    
        parsed_size_text = None
        major_size_mm = None
        if candidates:
            best = sorted(candidates, key=lambda c: (not c['is_secondary'], c['num_dims'], c['max_val']), reverse=True)[0]
            parsed_size_text = best['raw']
            major_size_mm = best['max_val']
            
        # Scoring Rules
        # Material Score: No Stone=0, Synthetic stone=5, Pearl=7, Natural stone=8, Diamond=10
        material_scores = {
            'No Stone': 0,
            'Synthetic stone': 5,
            'Pearl': 7,
            'Natural stone': 8,
            'Diamond': 10
        }
        material_score = material_scores.get(stype, None)
        
        # Shape Score
        gem_shape_scores = {
            'Round': 5, 'Oval': 6, 'Cushion': 6, 'Baguette': 7, 'Rectangle': 7,
            'Pear': 8, 'Drop': 8, 'Egg': 8, 'Onion': 8, 'Princess': 8,
            'Marquise': 9, 'Trillion': 9, 'Emerald Cut': 9, 'Heart': 10, 'Star': 10
        }
        pearl_shape_scores = {
            'Round': 5, 'Near Round': 6, 'Button': 6, 'Oval': 7, 'Potato': 7,
            'Coin / UFO / Mabe': 7, 'Rice': 8, 'Drop': 9, 'Baroque': 10
        }
        if is_pearl:
            shape_score = pearl_shape_scores.get(stone_shape, 5)
        else:
            shape_score = gem_shape_scores.get(stone_shape, 5)
            
        # Unit Size Score
        unit_size_score = None
        unit_size_source = None
        score_note = []
        
        if is_pearl:
            if major_size_mm is not None:
                unit_size_source = "Pearl mm"
                sz = major_size_mm
                if sz <= 3.0:
                    unit_size_score = 1
                elif sz <= 4.0:
                    unit_size_score = 2
                elif sz <= 5.0:
                    unit_size_score = 3
                elif sz <= 6.0:
                    unit_size_score = 4
                elif sz <= 7.0:
                    unit_size_score = 5
                elif sz <= 8.0:
                    unit_size_score = 6
                elif sz <= 9.0:
                    unit_size_score = 7
                elif sz <= 10.5:
                    unit_size_score = 8
                elif sz <= 12.0:
                    unit_size_score = 9
                else:
                    unit_size_score = 10
            else:
                unit_size_source = "Missing"
                score_note.append("Pearl missing mm size")
        else:
            if unit_weight_ct is not None:
                unit_size_source = "Carat"
                ct = unit_weight_ct
                if ct <= 0.005:
                    unit_size_score = 1
                elif ct <= 0.015:
                    unit_size_score = 2
                elif ct <= 0.035:
                    unit_size_score = 3
                elif ct <= 0.085:
                    unit_size_score = 4
                elif ct <= 0.22:
                    unit_size_score = 5
                elif ct <= 0.55:
                    unit_size_score = 6
                elif ct <= 1.30:
                    unit_size_score = 7
                elif ct <= 3.00:
                    unit_size_score = 8
                elif ct <= 6.00:
                    unit_size_score = 9
                else:
                    unit_size_score = 10
            else:
                if major_size_mm is not None:
                    unit_size_source = "mm fallback pending calibration"
                    unit_size_score = None
                    score_note.append("Non-pearl carat missing; mm parsed but pending calibration")
                else:
                    unit_size_source = "Missing"
                    unit_size_score = None
                    score_note.append("Non-pearl missing weight and mm")
                    
        if stype == 'Old stone (unspecified)':
            score_note.append("Material is unspecified/old stone")
            
        if pearl_mismatch:
            score_note.append("Pearl-like shape on non-pearl material")
            
        return {
            'StoneType': stype,
            'ShapeFamily': shape_family,
            'StoneShape': stone_shape,
            'ShapeSource': shape_source,
            'CutProfile': cut_profile,
            'PearlDrillType': drill_type,
            'UnitWeightGram': known_weight_g,
            'UnitWeightCarat': unit_weight_ct,
            'MajorSizeMm': major_size_mm,
            'ParsedSizeText': parsed_size_text,
            'PearlLikeMaterialMismatch': pearl_mismatch,
            'ProductName': pname,
            'MaterialScore': material_score,
            'ShapeScore': shape_score,
            'UnitSizeScore': unit_size_score,
            'UnitSizeSource': unit_size_source,
            'ScoreNote': "; ".join(score_note) if score_note else None
        }

    # Pre-parse all 625 Stone SKUs
    unique_skus = set(df_paths['StoneSKU'].unique())
    sku_parsed_map = {sku: parse_stone(sku) for sku in unique_skus}
    
    # Build Detail DataFrame
    detail_records = []
    for _, r in semi_stone_agg.iterrows():
        semi = r['SemiBOM']
        sku = r['StoneSKU']
        eff_cnt = r['EffectiveStoneCount']
        info = sku_parsed_map[sku]
        
        detail_records.append({
            'SemiBOM': semi,
            'Representative FG BOM': rep_fg_boms[semi],
            'Stone SKU': sku,
            'Stone Type': info['StoneType'],
            'Shape Family': info['ShapeFamily'],
            'Stone Shape': info['StoneShape'],
            'Shape Source': info['ShapeSource'],
            'Cut Profile': info['CutProfile'],
            'Pearl Drill Type': info['PearlDrillType'],
            'Effective Stone Count': eff_cnt,
            'Unit Weight (g)': info['UnitWeightGram'],
            'Unit Weight (ct)': info['UnitWeightCarat'],
            'Major Size (mm)': info['MajorSizeMm'],
            'Parsed Size Text': info['ParsedSizeText'],
            'Pearl-like Material Mismatch': 'Yes' if info['PearlLikeMaterialMismatch'] else 'No',
            'Product Name': info['ProductName'],
            'Material Score': info['MaterialScore'],
            'Shape Score': info['ShapeScore'],
            'Unit Size Score': info['UnitSizeScore'],
            'Unit Size Source': info['UnitSizeSource'],
            'Score Note': info['ScoreNote']
        })
        
    df_detail = pd.DataFrame(detail_records)
    print(f"Detail records prepared: {len(df_detail)}")
    
    # 4. Build Semi Summary Data
    summary_records = []
    for semi, group in df_detail.groupby('SemiBOM'):
        rep_fg = rep_fg_boms[semi]
        fg_cnt = fg_use_counts[semi]
        tot_cnt = group['Effective Stone Count'].sum()
        dist_sku = group['Stone SKU'].nunique()
        
        # Quantities by Material
        dia_qty = group[group['Stone Type'] == 'Diamond']['Effective Stone Count'].sum()
        nat_qty = group[group['Stone Type'] == 'Natural stone']['Effective Stone Count'].sum()
        art_qty = group[group['Stone Type'] == 'Synthetic stone']['Effective Stone Count'].sum()
        pearl_qty = group[group['Stone Type'] == 'Pearl']['Effective Stone Count'].sum()
        old_qty = group[group['Stone Type'] == 'Old stone (unspecified)']['Effective Stone Count'].sum()
        
        stype_list = "; ".join(sorted(group['Stone Type'].unique()))
        shape_list = "; ".join(sorted(group['Stone Shape'].unique()))
        
        # Composition formatted string
        comp_parts = []
        for _, dr in group.iterrows():
            c = int(dr['Effective Stone Count']) if dr['Effective Stone Count'] == int(dr['Effective Stone Count']) else dr['Effective Stone Count']
            st = dr['Stone Type']
            sh = dr['Stone Shape']
            sku = dr['Stone SKU']
            fam = dr['Shape Family']
            wt_ct = dr['Unit Weight (ct)']
            sz_mm = dr['Major Size (mm)']
            
            if fam == "Pearl":
                if pd.notna(sz_mm):
                    sz_str = f"{float(sz_mm):.2f}".rstrip('0').rstrip('.') + " mm"
                elif pd.notna(wt_ct):
                    sz_str = f"{float(wt_ct):.4f}".rstrip('0').rstrip('.') + " ct"
                else:
                    sz_str = "no size"
            else:
                if pd.notna(wt_ct):
                    sz_str = f"{float(wt_ct):.4f}".rstrip('0').rstrip('.') + " ct"
                elif pd.notna(sz_mm):
                    sz_str = f"{float(sz_mm):.2f}".rstrip('0').rstrip('.') + " mm"
                else:
                    sz_str = "no size"
            comp_parts.append(f"{c} × {st} {sh} ({sz_str}) [SKU {sku}]")
        stone_comp = " | ".join(comp_parts)
        
        # Material Score = MAX of non-null material scores
        valid_mat_scores = group['Material Score'].dropna()
        material_score = valid_mat_scores.max() if len(valid_mat_scores) > 0 else None
        
        # Shape Component
        max_shape_score = group['Shape Score'].max()
        avg_shape_score = (group['Shape Score'] * group['Effective Stone Count']).sum() / tot_cnt
        shape_component = 0.70 * max_shape_score + 0.30 * avg_shape_score
        
        # Count Score
        if tot_cnt == 0:
            count_score = 0
        elif tot_cnt == 1:
            count_score = 1
        elif tot_cnt == 2:
            count_score = 2
        elif 3 <= tot_cnt <= 4:
            count_score = 3
        elif 5 <= tot_cnt <= 9:
            count_score = 4
        elif 10 <= tot_cnt <= 20:
            count_score = 5
        elif 21 <= tot_cnt <= 39:
            count_score = 6
        elif 40 <= tot_cnt <= 76:
            count_score = 7
        elif 77 <= tot_cnt <= 149:
            count_score = 8
        elif 150 <= tot_cnt <= 359:
            count_score = 9
        else:
            count_score = 10
            
        # Size Component
        size_group = group[group['Unit Size Score'].notna()]
        if len(size_group) > 0:
            largest_size_score = size_group['Unit Size Score'].max()
            eff_cnt_with_size = size_group['Effective Stone Count'].sum()
            avg_size_score = (size_group['Unit Size Score'] * size_group['Effective Stone Count']).sum() / eff_cnt_with_size
            size_component = 0.75 * largest_size_score + 0.25 * avg_size_score
        else:
            largest_size_score = None
            avg_size_score = None
            size_component = None
            
        # Missing notes
        missing_notes = []
        if material_score is None:
            missing_notes.append("Material score missing (unspecified stone)")
        if len(size_group) == 0:
            missing_notes.append("Size score missing for all stones")
        elif len(size_group) < len(group):
            missing_notes.append(f"{len(group) - len(size_group)} of {len(group)} SKUs missing size score")
            
        is_complete = (material_score is not None) and (len(size_group) == len(group)) and (size_component is not None)
        
        # Python calculated reference scores
        if is_complete:
            status = "Complete"
            strict_score = round(material_score * 0.25 + shape_component * 0.20 + count_score * 0.15 + size_component * 0.40, 2)
            prov_score = strict_score
        else:
            status = "Provisional"
            strict_score = None
            # Provisional calculation
            avail = []
            if material_score is not None:
                avail.append((material_score, 0.25))
            if shape_component is not None:
                avail.append((shape_component, 0.20))
            if count_score is not None:
                avail.append((count_score, 0.15))
            if size_component is not None:
                avail.append((size_component, 0.40))
            if avail:
                tw = sum(a[1] for a in avail)
                prov_score = round(sum(a[0] * a[1] for a in avail) / tw, 2)
            else:
                prov_score = None
                status = "Missing"
                
        summary_records.append({
            'SemiBOM': semi,
            'Representative FG BOM': rep_fg,
            'FG Use Count': fg_cnt,
            'Total Stone Count': tot_cnt,
            'Distinct Stone SKU': dist_sku,
            'Stone Type List': stype_list,
            'Shape List': shape_list,
            'Diamond Qty': dia_qty,
            'Natural Stone Qty': nat_qty,
            'Synthetic stone Qty': art_qty,
            'Pearl Qty': pearl_qty,
            'Old/Unspecified Qty': old_qty,
            'Stone Composition': stone_comp,
            'Material Score': material_score,
            'Max Shape Score': max_shape_score,
            'Avg Shape Score': round(avg_shape_score, 2),
            'Shape Component': round(shape_component, 2),
            'Count Score': count_score,
            'Largest Size Score': largest_size_score,
            'Avg Size Score': round(avg_size_score, 2) if avg_size_score is not None else None,
            'Size Component': round(size_component, 2) if size_component is not None else None,
            'Strict Stone Complexity': strict_score,
            'Provisional Stone Complexity': prov_score,
            'Score Status': status,
            'Missing / Pending Note': "; ".join(missing_notes) if missing_notes else None,
            'Model Version': 'v1.0-pilot'
        })
        
    df_summary = pd.DataFrame(summary_records)
    print(f"Summary records prepared: {len(df_summary)}")
    
    # 5. Create Workbook with openpyxl
    print("Building workbook...")
    wb = openpyxl.Workbook()
    wb.remove(wb.active) # Remove default sheet
    
    # Enable automatic formula calculation on load in Excel
    wb.calculation.calcMode = 'auto'
    wb.calculation.fullCalcOnLoad = True
    
    # Color palette
    NAVY_HEADER = "1F4E79"
    SLATE_HEADER = "2F5597"
    LIGHT_BLUE = "D9E1F2"
    ZEBRA_FILL = "F9FAFC"
    WHITE = "FFFFFF"
    BORDER_COLOR = "D3D3D3"
    
    font_title = Font(name="Segoe UI", size=14, bold=True, color="1F4E79")
    font_section = Font(name="Segoe UI", size=11, bold=True, color="1F4E79")
    font_header = Font(name="Segoe UI", size=10, bold=True, color=WHITE)
    font_body = Font(name="Segoe UI", size=10)
    font_body_bold = Font(name="Segoe UI", size=10, bold=True)
    
    fill_header_navy = PatternFill(start_color=NAVY_HEADER, end_color=NAVY_HEADER, fill_type="solid")
    fill_header_slate = PatternFill(start_color=SLATE_HEADER, end_color=SLATE_HEADER, fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color=BORDER_COLOR),
        right=Side(style='thin', color=BORDER_COLOR),
        top=Side(style='thin', color=BORDER_COLOR),
        bottom=Side(style='thin', color=BORDER_COLOR)
    )
    
    def auto_fit_columns(ws, max_cols=None, max_width_limit=60):
        cols = list(ws.columns) if max_cols is None else list(ws.columns)[:max_cols]
        for col in cols:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in [1, 2] and cell.value and len(str(cell.value)) > 40:
                    continue
                if cell.value is not None:
                    val_str = str(cell.value)
                    lines = val_str.split('\n')
                    for l in lines:
                        if len(l) > max_len:
                            max_len = len(l)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 11), max_width_limit)
            
    # ==========================================
    # SHEET 1: README
    # ==========================================
    ws_readme = wb.create_sheet(title="README")
    ws_readme.views.sheetView[0].showGridLines = True
    
    readme_lines = [
        ("STONE COMPLEXITY SCORING MODEL PER SEMI-BOM", font_title),
        ("", font_body),
        ("1. EXECUTIVE SUMMARY & MODEL OVERVIEW", font_section),
        ("This workbook provides an end-to-end Stone Complexity scoring model for semi-finished jewelry assemblies (SemiBOM).", font_body),
        ("The scoring framework quantifies technical manufacturing difficulty across four key dimensions: Material, Shape, Count, and Size.", font_body),
        ("Output grain is strictly 1 row = 1 SemiBOM. Multi-FG BOM paths are normalized without Synthetic stone duplication.", font_body),
        ("", font_body),
        ("2. KEY SCORING COMPONENTS & PILOT WEIGHTS", font_section),
        ("• Material Score (25%): Natural break difficulty (Diamond=10, Natural stone=8, Pearl=7, Synthetic stone=5, No Stone=0). Multi-stone Semis take MAX.", font_body),
        ("• Shape Component (20%): Blended score = 70% Max Shape Score + 30% Quantity-weighted Average Shape Score across all stones.", font_body),
        ("• Count Score (15%): Natural break threshold scale (0 to 10) based on Total Effective Stone Count on the Semi.", font_body),
        ("• Size Component (40%): Dominant factor reflecting setting delicacy = 75% Largest Size Score + 25% Quantity-weighted Average Size Score.", font_body),
        ("   - Non-Pearl stones are scored using Unit Weight in Carats (1 g = 5 ct).", font_body),
        ("   - Pearl stones are scored using physical Major Dimension in Millimeters (mm).", font_body),
        ("", font_body),
        ("3. STRICT VS. PROVISIONAL COMPLEXITY", font_section),
        ("• Strict Stone Complexity: Calculated only when 100% of stone components (Material, Shape, Count, Size) are fully populated.", font_body),
        ("• Provisional Stone Complexity: Dynamically re-normalizes weights across available components when non-pearl weight/size is pending calibration.", font_body),
        ("  Missing data is NEVER defaulted to 0 difficulty, ensuring conservative and fair scoring.", font_body),
        ("", font_body),
        ("4. WORKBOOK STRUCTURE & SHEETS", font_section),
        ("1. README: Project documentation, taxonomy rules, and navigation guide.", font_body),
        ("2. Model Formula: Parameter weights and formula controls (editable).", font_body),
        ("3. Rule Material: Material taxonomy scores and multi-material rules.", font_body),
        ("4. Rule Gem Shape: Canonical gemstone shapes, scores, and typo corrections.", font_body),
        ("5. Rule Pearl Shape: Pearl shape priority taxonomy, default vs explicit rules.", font_body),
        ("6. Rule Stone Count: Natural-break count brackets and scores.", font_body),
        ("7. Rule Size Carat: Carat thresholds for non-pearl gemstones.", font_body),
        ("8. Rule Pearl mm: Physical mm size brackets for pearls.", font_body),
        ("9. Pending Setting: Future engineering factors (Grooves, Seats, Setting methods).", font_body),
        ("10. Semi Summary: Master summary table at grain 1 row = 1 SemiBOM (with live formulas).", font_body),
        ("11. Semi Stone Detail: Granular stone-level BOM detail table (SemiBOM + StoneSKU).", font_body),
    ]
    for r_idx, (text, f) in enumerate(readme_lines, start=1):
        c = ws_readme.cell(row=r_idx, column=1, value=text)
        c.font = f
    ws_readme.column_dimensions['A'].width = 125
    
    # ==========================================
    # SHEET 2: Model Formula
    # ==========================================
    ws_formula = wb.create_sheet(title="Model Formula")
    ws_formula.views.sheetView[0].showGridLines = True
    
    ws_formula.cell(row=1, column=1, value="MODEL FORMULA & CONFIGURABLE WEIGHTS").font = font_title
    
    # Section 1: Final Complexity Weights
    ws_formula.cell(row=3, column=1, value="1. Final Stone Complexity Weights (Sum = 100%)").font = font_section
    headers_f = ["Component", "Code / Range", "Weight", "Display %", "Description"]
    for c_idx, h in enumerate(headers_f, start=1):
        cell = ws_formula.cell(row=4, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
        
    weights_data = [
        ("Material", "W_MATERIAL", 0.25, "25.0%", "Weight of Material Score (MAX material on Semi)"),
        ("Shape", "W_SHAPE", 0.20, "20.0%", "Weight of Shape Component (70% Max + 30% Avg)"),
        ("Count", "W_COUNT", 0.15, "15.0%", "Weight of Stone Count Score (Natural break thresholds)"),
        ("Size", "W_SIZE", 0.40, "40.0%", "Weight of Size Component (75% Largest + 25% Avg)"),
    ]
    for idx, (comp, code, wt, pct, desc) in enumerate(weights_data, start=5):
        ws_formula.cell(row=idx, column=1, value=comp).border = thin_border
        ws_formula.cell(row=idx, column=2, value=code).border = thin_border
        c_wt = ws_formula.cell(row=idx, column=3, value=wt)
        c_wt.number_format = '0.00'
        c_wt.border = thin_border
        c_wt.font = font_body_bold
        ws_formula.cell(row=idx, column=4, value=pct).border = thin_border
        ws_formula.cell(row=idx, column=5, value=desc).border = thin_border
        
    ws_formula.cell(row=9, column=1, value="Total Check").font = font_body_bold
    ws_formula.cell(row=9, column=1).border = thin_border
    ws_formula.cell(row=9, column=2, value="SUM(C5:C8)").border = thin_border
    c_tot = ws_formula.cell(row=9, column=3, value="=SUM(C5:C8)")
    c_tot.font = font_body_bold
    c_tot.number_format = '0.00'
    c_tot.border = thin_border
    ws_formula.cell(row=9, column=4, value="100.0%").border = thin_border
    ws_formula.cell(row=9, column=5, value="Must always sum to 1.00 (100%)").border = thin_border
    
    # Section 2: Shape Component Internal Weights
    ws_formula.cell(row=11, column=1, value="2. Shape Component Internal Weights").font = font_section
    for c_idx, h in enumerate(["Shape Sub-Factor", "Code", "Internal Weight", "Display %", "Description"], start=1):
        cell = ws_formula.cell(row=12, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_slate
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
        
    shape_internal = [
        ("Max Shape Score", "W_SHAPE_MAX", 0.70, "70.0%", "Weight allocated to the single most difficult shape on Semi"),
        ("Avg Shape Score", "W_SHAPE_AVG", 0.30, "30.0%", "Weight allocated to quantity-weighted average shape score"),
    ]
    for idx, (subf, code, wt, pct, desc) in enumerate(shape_internal, start=13):
        ws_formula.cell(row=idx, column=1, value=subf).border = thin_border
        ws_formula.cell(row=idx, column=2, value=code).border = thin_border
        c_wt = ws_formula.cell(row=idx, column=3, value=wt)
        c_wt.number_format = '0.00'
        c_wt.border = thin_border
        c_wt.font = font_body_bold
        ws_formula.cell(row=idx, column=4, value=pct).border = thin_border
        ws_formula.cell(row=idx, column=5, value=desc).border = thin_border
        
    ws_formula.cell(row=15, column=1, value="Total Check").font = font_body_bold
    ws_formula.cell(row=15, column=1).border = thin_border
    ws_formula.cell(row=15, column=2, value="SUM(C13:C14)").border = thin_border
    c_tot_s = ws_formula.cell(row=15, column=3, value="=SUM(C13:C14)")
    c_tot_s.font = font_body_bold
    c_tot_s.number_format = '0.00'
    c_tot_s.border = thin_border
    ws_formula.cell(row=15, column=4, value="100.0%").border = thin_border
    ws_formula.cell(row=15, column=5, value="Must always sum to 1.00").border = thin_border

    # Section 3: Size Component Internal Weights
    ws_formula.cell(row=17, column=1, value="3. Size Component Internal Weights").font = font_section
    for c_idx, h in enumerate(["Size Sub-Factor", "Code", "Internal Weight", "Display %", "Description"], start=1):
        cell = ws_formula.cell(row=18, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_slate
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
        
    size_internal = [
        ("Largest Size Score", "W_SIZE_MAX", 0.75, "75.0%", "Weight allocated to largest stone size score on Semi (30% effective final)"),
        ("Avg Size Score", "W_SIZE_AVG", 0.25, "25.0%", "Weight allocated to quantity-weighted average size score (10% effective final)"),
    ]
    for idx, (subf, code, wt, pct, desc) in enumerate(size_internal, start=19):
        ws_formula.cell(row=idx, column=1, value=subf).border = thin_border
        ws_formula.cell(row=idx, column=2, value=code).border = thin_border
        c_wt = ws_formula.cell(row=idx, column=3, value=wt)
        c_wt.number_format = '0.00'
        c_wt.border = thin_border
        c_wt.font = font_body_bold
        ws_formula.cell(row=idx, column=4, value=pct).border = thin_border
        ws_formula.cell(row=idx, column=5, value=desc).border = thin_border
        
    ws_formula.cell(row=21, column=1, value="Total Check").font = font_body_bold
    ws_formula.cell(row=21, column=1).border = thin_border
    ws_formula.cell(row=21, column=2, value="SUM(C19:C20)").border = thin_border
    c_tot_z = ws_formula.cell(row=21, column=3, value="=SUM(C19:C20)")
    c_tot_z.font = font_body_bold
    c_tot_z.number_format = '0.00'
    c_tot_z.border = thin_border
    ws_formula.cell(row=21, column=4, value="100.0%").border = thin_border
    ws_formula.cell(row=21, column=5, value="Must always sum to 1.00").border = thin_border
    
    auto_fit_columns(ws_formula)
    
    # ==========================================
    # SHEET 3: Rule Material
    # ==========================================
    ws_mat = wb.create_sheet(title="Rule Material")
    ws_mat.views.sheetView[0].showGridLines = True
    ws_mat.cell(row=1, column=1, value="STONE MATERIAL TAXONOMY & SCORING RULES").font = font_title
    
    headers_mat = ["Stone Material", "Material Score", "Rationale & Handling Rules"]
    for c_idx, h in enumerate(headers_mat, start=1):
        cell = ws_mat.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    mat_rows = [
        ("No Stone", 0, "No stone setting required on Semi assembly"),
        ("Synthetic stone", 5, "Standard synthetic stones (e.g. CZ, synthetic crystal, glass)"),
        ("Pearl", 7, "Organic pearls (Freshwater, Mabe, etc.) requiring delicate setting"),
        ("Natural stone", 8, "Colored gemstones (Emerald, Sapphire, Quartz, Moonstone, Onyx, Topaz)"),
        ("Diamond", 10, "Natural diamonds requiring precision micro-prong / master setting"),
        ("Old stone (unspecified)", "NULL / TBD", "Legacy unclassified stone. Flagged for review, never defaulted to 0"),
    ]
    for idx, (m_name, m_sc, r_note) in enumerate(mat_rows, start=4):
        ws_mat.cell(row=idx, column=1, value=m_name).border = thin_border
        c_s = ws_mat.cell(row=idx, column=2, value=m_sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_mat.cell(row=idx, column=3, value=r_note).border = thin_border
        
    ws_mat.cell(row=11, column=1, value="Aggregation Rule on Semi:").font = font_section
    ws_mat.cell(row=12, column=1, value="If a Semi contains multiple materials: MaterialScore = MAX(MaterialScore of stones present).").font = font_body
    auto_fit_columns(ws_mat)
    
    # ==========================================
    # SHEET 4: Rule Gem Shape
    # ==========================================
    ws_gem = wb.create_sheet(title="Rule Gem Shape")
    ws_gem.views.sheetView[0].showGridLines = True
    ws_gem.cell(row=1, column=1, value="CANONICAL GEMSTONE SHAPE TAXONOMY & SCORING").font = font_title
    
    headers_gem = ["Gemstone Shape", "Score", "Shape Category / Difficulty Rationale"]
    for c_idx, h in enumerate(headers_gem, start=1):
        cell = ws_gem.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    gem_rows = [
        ("Round", 5, "Standard symmetrical round brilliant / facet. Easiest alignment"),
        ("Oval", 6, "Slight elongation requiring orientation control"),
        ("Cushion", 6, "Curved rectangle/square with corner delicacy"),
        ("Baguette", 7, "Step-cut straight edges requiring precise parallel alignment"),
        ("Rectangle", 7, "Sharp cornered rectangular stones"),
        ("Pear", 8, "Asymmetric teardrop contour requiring tip protection"),
        ("Drop", 8, "Briolette/drop profile stone"),
        ("Egg", 8, "Egg-shaped cabochon or facet"),
        ("Onion", 8, "Bulbous onion briolette cut"),
        ("Princess", 8, "Square brilliant cut with 4 vulnerable point corners"),
        ("Marquise", 9, "Double-pointed boat shape, two delicate tips"),
        ("Trillion", 9, "Triangular cut with 3 vulnerable corners"),
        ("Emerald Cut", 9, "Octagonal step cut requiring flawless seat leveling"),
        ("Heart", 10, "Cleft and point shape requiring complex prong / bezel shaping"),
        ("Star", 10, "Multi-point star shape with highest setting failure risk"),
    ]
    for idx, (g_sh, sc, r_note) in enumerate(gem_rows, start=4):
        ws_gem.cell(row=idx, column=1, value=g_sh).border = thin_border
        c_s = ws_gem.cell(row=idx, column=2, value=sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_gem.cell(row=idx, column=3, value=r_note).border = thin_border
        
    ws_gem.cell(row=20, column=1, value="Special Parsing & Taxonomy Rules:").font = font_section
    ws_gem.cell(row=21, column=1, value="• Typo Correction: 'Maquire' is automatically corrected to 'Marquise' (ShapeSource = 'Corrected').").font = font_body
    ws_gem.cell(row=22, column=1, value="• Emerald Material vs Cut: 'Emerald Round Cut' parses as Material = Emerald/Natural stone, Shape = Round.").font = font_body
    ws_gem.cell(row=23, column=1, value="• Cut Profiles (Brilliant, Cabochon, Rose Cut, Briolette, Step Cut, Faceted) are parsed separately and never mixed with Shape.").font = font_body
    auto_fit_columns(ws_gem)
    
    # ==========================================
    # SHEET 5: Rule Pearl Shape
    # ==========================================
    ws_pearl = wb.create_sheet(title="Rule Pearl Shape")
    ws_pearl.views.sheetView[0].showGridLines = True
    ws_pearl.cell(row=1, column=1, value="PEARL SHAPE TAXONOMY & PARSING PRIORITY").font = font_title
    
    headers_pearl = ["Priority", "Pearl Shape", "Score", "Description & Seating Characteristics"]
    for c_idx, h in enumerate(headers_pearl, start=1):
        cell = ws_pearl.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    pearl_rows = [
        (1, "Baroque", 10, "Irregular organic shape requiring custom hand-adjusted seat"),
        (2, "Potato", 7, "Slightly lumpy roundish freshwater pearl"),
        (3, "Rice", 8, "Elongated rice-grain profile requiring axial alignment"),
        (4, "Button", 6, "Flattened dome pearl, stable flat base for peg setting"),
        (5, "Near Round", 6, "Semi-round pearl with minor axis variation"),
        (6, "Oval", 7, "Symmetrical elongated pearl"),
        (7, "Drop", 9, "Teardrop shaped pearl requiring balanced pendant/cup setting"),
        (8, "Coin / UFO / Mabe", 7, "Flat circular or blister pearl"),
        (9, "Round", 5, "Spherical pearl, standard cup/peg setting (Default when unspecified)"),
    ]
    for idx, (prio, p_sh, sc, r_note) in enumerate(pearl_rows, start=4):
        ws_pearl.cell(row=idx, column=1, value=prio).border = thin_border
        ws_pearl.cell(row=idx, column=1).alignment = Alignment(horizontal="center")
        ws_pearl.cell(row=idx, column=2, value=p_sh).border = thin_border
        c_s = ws_pearl.cell(row=idx, column=3, value=sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_pearl.cell(row=idx, column=4, value=r_note).border = thin_border
        
    ws_pearl.cell(row=14, column=1, value="Pearl Identification & Material Integrity:").font = font_section
    ws_pearl.cell(row=15, column=1, value="• Pearl identification is parsed FIRST before gemstone shapes.").font = font_body
    ws_pearl.cell(row=16, column=1, value="• Glass/Imitation pearls (e.g. 'Glass Rice Pearl') retain StoneType = 'Synthetic stone' while ShapeFamily = 'Pearl'.").font = font_body
    ws_pearl.cell(row=17, column=1, value="• Flag 'PearlLikeMaterialMismatch' is raised for quality traceability.").font = font_body
    auto_fit_columns(ws_pearl)
    
    # ==========================================
    # SHEET 6: Rule Stone Count
    # ==========================================
    ws_count = wb.create_sheet(title="Rule Stone Count")
    ws_count.views.sheetView[0].showGridLines = True
    ws_count.cell(row=1, column=1, value="NATURAL BREAK STONE COUNT THRESHOLDS").font = font_title
    
    headers_cnt = ["Total Stone Count Bracket", "Score", "Complexity Rationale"]
    for c_idx, h in enumerate(headers_cnt, start=1):
        cell = ws_count.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    cnt_rows = [
        ("0 stones", 0, "No stones on Semi"),
        ("1 stone", 1, "Solitaire stone setting"),
        ("2 stones", 2, "Pair setting (e.g. earrings, twin side stones)"),
        ("3–4 stones", 3, "Triad / 4-stone cluster"),
        ("5–9 stones", 4, "Small multi-stone arrangement"),
        ("10–20 stones", 5, "Medium pavé / halo setting"),
        ("21–39 stones", 6, "Extended multi-stone band / halo"),
        ("40–76 stones", 7, "High-density micro-pavé"),
        ("77–149 stones", 8, "Very dense multi-row pavé"),
        ("150–359 stones", 9, "Extremely complex pave coverage"),
        (">= 360 stones", 10, "Maximum complexity pavé masterpiece"),
    ]
    for idx, (brk, sc, r_note) in enumerate(cnt_rows, start=4):
        ws_count.cell(row=idx, column=1, value=brk).border = thin_border
        c_s = ws_count.cell(row=idx, column=2, value=sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_count.cell(row=idx, column=3, value=r_note).border = thin_border
        
    auto_fit_columns(ws_count)
    
    # ==========================================
    # SHEET 7: Rule Size Carat
    # ==========================================
    ws_carat = wb.create_sheet(title="Rule Size Carat")
    ws_carat.views.sheetView[0].showGridLines = True
    ws_carat.cell(row=1, column=1, value="UNIT SIZE THRESHOLDS — NON-PEARL GEMSTONES (CARAT)").font = font_title
    
    headers_carat = ["Unit Weight Carat (ct)", "Score", "Applicable Stone Types", "Handling Rules"]
    for c_idx, h in enumerate(headers_carat, start=1):
        cell = ws_carat.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    carat_rows = [
        ("<= 0.005 ct", 1, "Diamond, Natural stone, Synthetic stone", "Micro stones / melee"),
        ("> 0.005 – 0.015 ct", 2, "Diamond, Natural stone, Synthetic stone", "Small melee stones"),
        ("> 0.015 – 0.035 ct", 3, "Diamond, Natural stone, Synthetic stone", "Standard pavé size"),
        ("> 0.035 – 0.085 ct", 4, "Diamond, Natural stone, Synthetic stone", "Medium accent stones"),
        ("> 0.085 – 0.22 ct", 5, "Diamond, Natural stone, Synthetic stone", "Prominent accent stones"),
        ("> 0.22 – 0.55 ct", 6, "Diamond, Natural stone, Synthetic stone", "Quarter to half carat stones"),
        ("> 0.55 – 1.30 ct", 7, "Diamond, Natural stone, Synthetic stone", "Substantial centerpiece size"),
        ("> 1.30 – 3.00 ct", 8, "Diamond, Natural stone, Synthetic stone", "Large centerpiece gemstones"),
        ("> 3.00 – 6.00 ct", 9, "Diamond, Natural stone, Synthetic stone", "Very large gemstones"),
        ("> 6.00 ct", 10, "Diamond, Natural stone, Synthetic stone", "Exceptional / oversized gemstones"),
    ]
    for idx, (brk, sc, app, r_note) in enumerate(carat_rows, start=4):
        ws_carat.cell(row=idx, column=1, value=brk).border = thin_border
        c_s = ws_carat.cell(row=idx, column=2, value=sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_carat.cell(row=idx, column=3, value=app).border = thin_border
        ws_carat.cell(row=idx, column=4, value=r_note).border = thin_border
        
    ws_carat.cell(row=15, column=1, value="Conversion & Pending Calibration Rules:").font = font_section
    ws_carat.cell(row=16, column=1, value="• Conversion: UnitWeightCarat = KnownUnitWeightGram * 5.0 (1 gram = 5 carats).").font = font_body
    ws_carat.cell(row=17, column=1, value="• Non-pearl stones missing weight but having physical mm size are assigned UnitSizeScore = NULL with source 'mm fallback pending calibration'.").font = font_body
    auto_fit_columns(ws_carat)
    
    # ==========================================
    # SHEET 8: Rule Pearl mm
    # ==========================================
    ws_pmm = wb.create_sheet(title="Rule Pearl mm")
    ws_pmm.views.sheetView[0].showGridLines = True
    ws_pmm.cell(row=1, column=1, value="UNIT SIZE THRESHOLDS — PEARLS (MAJOR PHYSICAL MM)").font = font_title
    
    headers_pmm = ["Pearl Major Size (mm)", "Score", "Applicable Stone Types", "Handling Rules"]
    for c_idx, h in enumerate(headers_pmm, start=1):
        cell = ws_pmm.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    pmm_rows = [
        ("<= 3.0 mm", 1, "Pearl, Pearl-like stones", "Seed pearls / micro pearls"),
        ("> 3.0 – 4.0 mm", 2, "Pearl, Pearl-like stones", "Small freshwater pearls"),
        ("> 4.0 – 5.0 mm", 3, "Pearl, Pearl-like stones", "Medium-small pearls"),
        ("> 5.0 – 6.0 mm", 4, "Pearl, Pearl-like stones", "Medium pearls"),
        ("> 6.0 – 7.0 mm", 5, "Pearl, Pearl-like stones", "Standard jewelry pearls"),
        ("> 7.0 – 8.0 mm", 6, "Pearl, Pearl-like stones", "Prominent pearls"),
        ("> 8.0 – 9.0 mm", 7, "Pearl, Pearl-like stones", "Large luxury pearls"),
        ("> 9.0 – 10.5 mm", 8, "Pearl, Pearl-like stones", "Very large focal pearls"),
        ("> 10.5 – 12.0 mm", 9, "Pearl, Pearl-like stones", "Oversized pearls"),
        ("> 12.0 mm", 10, "Pearl, Pearl-like stones", "Grand / statement pearls"),
    ]
    for idx, (brk, sc, app, r_note) in enumerate(pmm_rows, start=4):
        ws_pmm.cell(row=idx, column=1, value=brk).border = thin_border
        c_s = ws_pmm.cell(row=idx, column=2, value=sc)
        c_s.border = thin_border
        c_s.alignment = Alignment(horizontal="center")
        c_s.font = font_body_bold
        ws_pmm.cell(row=idx, column=3, value=app).border = thin_border
        ws_pmm.cell(row=idx, column=4, value=r_note).border = thin_border
        
    ws_pmm.cell(row=15, column=1, value="Pearl Size Principle:").font = font_section
    ws_pmm.cell(row=16, column=1, value="• Pearls NEVER use carat weight for size scoring. Physical mm dimension represents actual seating volume and delicate cup fitting.").font = font_body
    auto_fit_columns(ws_pmm)
    
    # ==========================================
    # SHEET 9: Pending Setting
    # ==========================================
    ws_pend = wb.create_sheet(title="Pending Setting")
    ws_pend.views.sheetView[0].showGridLines = True
    ws_pend.cell(row=1, column=1, value="PENDING FACTORS — GROOVES, SEATS & SETTING METHODS").font = font_title
    
    headers_pend = ["Pending Factor", "Current Status", "Engineering Notes & Formula Blueprint"]
    for c_idx, h in enumerate(headers_pend, start=1):
        cell = ws_pend.cell(row=3, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.border = thin_border
        
    pend_rows = [
        ("Groove / Seat Count", "Pending CAD Integration", "Groove Count must be tracked separately from Stone Count. 10 stones in 1 groove != 20 stones in 4 grooves."),
        ("Stones per Groove", "Pending CAD Integration", "Density metric: Ratio of StoneCount / GrooveCount influences tool wear and vibration."),
        ("Seat Shape", "Pending Geometry Mapping", "Matching stone girdle shape to cast/milled seat geometry (Round vs Fancy cuts)."),
        ("Setting Method", "Pending Production Source", "Prong, Bezel, Press, Pavé, Channel, Flush. Currently held pending verified shop floor routing."),
        ("Setting Geometry Function", "Conceptual Blueprint", "Future Setting Geometry Score = f(StoneCount, GrooveCount, StonesPerGroove, SeatShape, Method)."),
    ]
    for idx, (fac, stat, note) in enumerate(pend_rows, start=4):
        ws_pend.cell(row=idx, column=1, value=fac).border = thin_border
        ws_pend.cell(row=idx, column=2, value=stat).border = thin_border
        ws_pend.cell(row=idx, column=2).alignment = Alignment(horizontal="center")
        ws_pend.cell(row=idx, column=3, value=note).border = thin_border
        
    auto_fit_columns(ws_pend)
    
    # ==========================================
    # SHEET 10: Semi Summary
    # ==========================================
    ws_sum = wb.create_sheet(title="Semi Summary")
    ws_sum.views.sheetView[0].showGridLines = True
    ws_sum.freeze_panes = "A2"
    
    headers_summary = [
        "SemiBOM", "Representative FG BOM", "FG Use Count", "Total Stone Count", "Distinct Stone SKU",
        "Stone Type List", "Shape List", "Diamond Qty", "Natural Stone Qty", "Synthetic stone Qty",
        "Pearl Qty", "Old/Unspecified Qty", "Stone Composition", "Material Score", "Max Shape Score",
        "Avg Shape Score", "Shape Component", "Count Score", "Largest Size Score", "Avg Size Score",
        "Size Component", "Strict Stone Complexity", "Provisional Stone Complexity", "Score Status",
        "Missing / Pending Note", "Model Version"
    ]
    
    for c_idx, h in enumerate(headers_summary, start=1):
        cell = ws_sum.cell(row=1, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        
    print("Writing Semi Summary rows with formulas...")
    for r_idx, r in df_summary.iterrows():
        row_num = r_idx + 2
        
        # Plain values
        ws_sum.cell(row=row_num, column=1, value=r['SemiBOM']).border = thin_border
        ws_sum.cell(row=row_num, column=2, value=r['Representative FG BOM']).border = thin_border
        c_use = ws_sum.cell(row=row_num, column=3, value=r['FG Use Count'])
        c_use.border = thin_border
        c_use.alignment = Alignment(horizontal="right")
        
        c_tot = ws_sum.cell(row=row_num, column=4, value=r['Total Stone Count'])
        c_tot.border = thin_border
        c_tot.alignment = Alignment(horizontal="right")
        
        c_sku = ws_sum.cell(row=row_num, column=5, value=r['Distinct Stone SKU'])
        c_sku.border = thin_border
        c_sku.alignment = Alignment(horizontal="right")
        
        ws_sum.cell(row=row_num, column=6, value=r['Stone Type List']).border = thin_border
        ws_sum.cell(row=row_num, column=7, value=r['Shape List']).border = thin_border
        
        # Quantities
        for q_idx, col_name in enumerate(['Diamond Qty', 'Natural Stone Qty', 'Synthetic stone Qty', 'Pearl Qty', 'Old/Unspecified Qty'], start=8):
            cell = ws_sum.cell(row=row_num, column=q_idx, value=r[col_name])
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="right")
            
        c_comp = ws_sum.cell(row=row_num, column=13, value=r['Stone Composition'])
        c_comp.border = thin_border
        c_comp.alignment = Alignment(wrap_text=True)
        
        # Scores
        c_mat = ws_sum.cell(row=row_num, column=14, value=r['Material Score'])
        c_mat.border = thin_border
        c_mat.alignment = Alignment(horizontal="right")
        if r['Material Score'] is not None:
            c_mat.number_format = '0.00'
            
        c_msh = ws_sum.cell(row=row_num, column=15, value=r['Max Shape Score'])
        c_msh.border = thin_border
        c_msh.alignment = Alignment(horizontal="right")
        c_msh.number_format = '0.00'
        
        c_ash = ws_sum.cell(row=row_num, column=16, value=r['Avg Shape Score'])
        c_ash.border = thin_border
        c_ash.alignment = Alignment(horizontal="right")
        c_ash.number_format = '0.00'
        
        # Shape Component Formula: 70% Max + 30% Avg
        # References 'Model Formula'!$C$13 and 'Model Formula'!$C$14
        c_shc = ws_sum.cell(row=row_num, column=17)
        c_shc.value = f"='Model Formula'!$C$13 * O{row_num} + 'Model Formula'!$C$14 * P{row_num}"
        c_shc.border = thin_border
        c_shc.alignment = Alignment(horizontal="right")
        c_shc.number_format = '0.00'
        
        c_cnt = ws_sum.cell(row=row_num, column=18, value=r['Count Score'])
        c_cnt.border = thin_border
        c_cnt.alignment = Alignment(horizontal="right")
        c_cnt.number_format = '0.00'
        
        c_lsz = ws_sum.cell(row=row_num, column=19, value=r['Largest Size Score'])
        c_lsz.border = thin_border
        c_lsz.alignment = Alignment(horizontal="right")
        if r['Largest Size Score'] is not None:
            c_lsz.number_format = '0.00'
            
        c_asz = ws_sum.cell(row=row_num, column=20, value=r['Avg Size Score'])
        c_asz.border = thin_border
        c_asz.alignment = Alignment(horizontal="right")
        if r['Avg Size Score'] is not None:
            c_asz.number_format = '0.00'
            
        # Size Component Formula: 75% Largest + 25% Avg
        # References 'Model Formula'!$C$19 and 'Model Formula'!$C$20
        c_szc = ws_sum.cell(row=row_num, column=21)
        c_szc.value = f'=IF(ISNUMBER(S{row_num}), \'Model Formula\'!$C$19 * S{row_num} + \'Model Formula\'!$C$20 * T{row_num}, "")'
        c_szc.border = thin_border
        c_szc.alignment = Alignment(horizontal="right")
        c_szc.number_format = '0.00'
        
        # Strict Stone Complexity Formula
        # =IF(X{row_num}="Complete", W{row_num}, "")
        c_stc = ws_sum.cell(row=row_num, column=22)
        c_stc.value = f'=IF(X{row_num}="Complete", W{row_num}, "")'
        c_stc.border = thin_border
        c_stc.alignment = Alignment(horizontal="right")
        c_stc.font = font_body_bold
        c_stc.number_format = '0.00'
        
        # Provisional Stone Complexity Formula (dynamic re-normalization)
        # References 'Model Formula'!$C$5 (Mat), $C$6 (Shape), $C$7 (Count), $C$8 (Size)
        num_expr = (
            f"IF(ISNUMBER(N{row_num}), N{row_num}*'Model Formula'!$C$5, 0) + "
            f"IF(ISNUMBER(Q{row_num}), Q{row_num}*'Model Formula'!$C$6, 0) + "
            f"IF(ISNUMBER(R{row_num}), R{row_num}*'Model Formula'!$C$7, 0) + "
            f"IF(ISNUMBER(U{row_num}), U{row_num}*'Model Formula'!$C$8, 0)"
        )
        den_expr = (
            f"IF(ISNUMBER(N{row_num}), 'Model Formula'!$C$5, 0) + "
            f"IF(ISNUMBER(Q{row_num}), 'Model Formula'!$C$6, 0) + "
            f"IF(ISNUMBER(R{row_num}), 'Model Formula'!$C$7, 0) + "
            f"IF(ISNUMBER(U{row_num}), 'Model Formula'!$C$8, 0)"
        )
        c_prv = ws_sum.cell(row=row_num, column=23)
        c_prv.value = f"=ROUND(({num_expr}) / ({den_expr}), 2)"
        c_prv.border = thin_border
        c_prv.alignment = Alignment(horizontal="right")
        c_prv.font = font_body_bold
        c_prv.number_format = '0.00'
        
        # Score Status
        c_sts = ws_sum.cell(row=row_num, column=24, value=r['Score Status'])
        c_sts.border = thin_border
        c_sts.alignment = Alignment(horizontal="center")
        c_sts.font = font_body_bold
        
        # Note & Version
        c_not = ws_sum.cell(row=row_num, column=25, value=r['Missing / Pending Note'])
        c_not.border = thin_border
        c_not.alignment = Alignment(wrap_text=True)
        
        c_ver = ws_sum.cell(row=row_num, column=26, value=r['Model Version'])
        c_ver.border = thin_border
        c_ver.alignment = Alignment(horizontal="center")
        
    # Auto filter on Semi Summary
    ws_sum.auto_filter.ref = f"A1:Z{len(df_summary) + 1}"
    
    # Conditional formatting for Score Status
    fill_complete = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    font_complete = Font(name="Segoe UI", size=10, bold=True, color="375623")
    fill_provisional = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    font_provisional = Font(name="Segoe UI", size=10, bold=True, color="806000")
    
    status_range = f"X2:X{len(df_summary) + 1}"
    ws_sum.conditional_formatting.add(status_range, CellIsRule(operator='equal', formula=['"Complete"'], fill=fill_complete, font=font_complete))
    ws_sum.conditional_formatting.add(status_range, CellIsRule(operator='equal', formula=['"Provisional"'], fill=fill_provisional, font=font_provisional))
    
    # Format column widths
    summary_col_widths = {
        'A': 22, 'B': 20, 'C': 12, 'D': 15, 'E': 16,
        'F': 22, 'G': 20, 'H': 13, 'I': 16, 'J': 16,
        'K': 12, 'L': 18, 'M': 50, 'N': 13, 'O': 14,
        'P': 14, 'Q': 15, 'R': 12, 'S': 16, 'T': 14,
        'U': 14, 'V': 20, 'W': 24, 'X': 15, 'Y': 35, 'Z': 14
    }
    for col_let, wid in summary_col_widths.items():
        ws_sum.column_dimensions[col_let].width = wid
        
    # ==========================================
    # SHEET 11: Semi Stone Detail
    # ==========================================
    ws_det = wb.create_sheet(title="Semi Stone Detail")
    ws_det.views.sheetView[0].showGridLines = True
    ws_det.freeze_panes = "A2"
    
    headers_detail = [
        "SemiBOM", "Representative FG BOM", "Stone SKU", "Stone Type", "Shape Family",
        "Stone Shape", "Shape Source", "Cut Profile", "Pearl Drill Type", "Effective Stone Count",
        "Unit Weight (g)", "Unit Weight (ct)", "Major Size (mm)", "Parsed Size Text",
        "Pearl-like Material Mismatch", "Product Name", "Material Score", "Shape Score",
        "Unit Size Score", "Unit Size Source", "Score Note"
    ]
    
    for c_idx, h in enumerate(headers_detail, start=1):
        cell = ws_det.cell(row=1, column=c_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header_navy
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        
    print("Writing Semi Stone Detail rows...")
    for r_idx, r in df_detail.iterrows():
        row_num = r_idx + 2
        ws_det.cell(row=row_num, column=1, value=r['SemiBOM']).border = thin_border
        ws_det.cell(row=row_num, column=2, value=r['Representative FG BOM']).border = thin_border
        ws_det.cell(row=row_num, column=3, value=r['Stone SKU']).border = thin_border
        ws_det.cell(row=row_num, column=4, value=r['Stone Type']).border = thin_border
        ws_det.cell(row=row_num, column=5, value=r['Shape Family']).border = thin_border
        ws_det.cell(row=row_num, column=6, value=r['Stone Shape']).border = thin_border
        ws_det.cell(row=row_num, column=7, value=r['Shape Source']).border = thin_border
        ws_det.cell(row=row_num, column=8, value=r['Cut Profile']).border = thin_border
        ws_det.cell(row=row_num, column=9, value=r['Pearl Drill Type']).border = thin_border
        
        c_cnt = ws_det.cell(row=row_num, column=10, value=r['Effective Stone Count'])
        c_cnt.border = thin_border
        c_cnt.alignment = Alignment(horizontal="right")
        
        c_wg = ws_det.cell(row=row_num, column=11, value=r['Unit Weight (g)'])
        c_wg.border = thin_border
        c_wg.alignment = Alignment(horizontal="right")
        if r['Unit Weight (g)'] is not None and pd.notna(r['Unit Weight (g)']):
            c_wg.number_format = '0.0000'
            
        c_wc = ws_det.cell(row=row_num, column=12, value=r['Unit Weight (ct)'])
        c_wc.border = thin_border
        c_wc.alignment = Alignment(horizontal="right")
        if r['Unit Weight (ct)'] is not None and pd.notna(r['Unit Weight (ct)']):
            c_wc.number_format = '0.0000'
            
        c_ms = ws_det.cell(row=row_num, column=13, value=r['Major Size (mm)'])
        c_ms.border = thin_border
        c_ms.alignment = Alignment(horizontal="right")
        if r['Major Size (mm)'] is not None and pd.notna(r['Major Size (mm)']):
            c_ms.number_format = '0.00'
            
        ws_det.cell(row=row_num, column=14, value=r['Parsed Size Text']).border = thin_border
        
        c_mis = ws_det.cell(row=row_num, column=15, value=r['Pearl-like Material Mismatch'])
        c_mis.border = thin_border
        c_mis.alignment = Alignment(horizontal="center")
        
        c_pn = ws_det.cell(row=row_num, column=16, value=r['Product Name'])
        c_pn.border = thin_border
        c_pn.alignment = Alignment(wrap_text=True)
        
        c_ms = ws_det.cell(row=row_num, column=17, value=r['Material Score'])
        c_ms.border = thin_border
        c_ms.alignment = Alignment(horizontal="right")
        
        c_ss = ws_det.cell(row=row_num, column=18, value=r['Shape Score'])
        c_ss.border = thin_border
        c_ss.alignment = Alignment(horizontal="right")
        
        c_uzs = ws_det.cell(row=row_num, column=19, value=r['Unit Size Score'])
        c_uzs.border = thin_border
        c_uzs.alignment = Alignment(horizontal="right")
        
        ws_det.cell(row=row_num, column=20, value=r['Unit Size Source']).border = thin_border
        
        c_sn = ws_det.cell(row=row_num, column=21, value=r['Score Note'])
        c_sn.border = thin_border
        c_sn.alignment = Alignment(wrap_text=True)
        
    ws_det.auto_filter.ref = f"A1:U{len(df_detail) + 1}"
    
    detail_col_widths = {
        'A': 22, 'B': 20, 'C': 12, 'D': 16, 'E': 14,
        'F': 14, 'G': 13, 'H': 20, 'I': 15, 'J': 18,
        'K': 14, 'L': 14, 'M': 15, 'N': 16, 'O': 24,
        'P': 45, 'Q': 14, 'R': 13, 'S': 14, 'T': 24, 'U': 35
    }
    for col_let, wid in detail_col_widths.items():
        ws_det.column_dimensions[col_let].width = wid
        
    # Save Workbook
    print(f"Saving workbook to {output_file}...")
    wb.save(output_file)
    print("Workbook successfully saved!")
    
    # Also copy the generation script into the target directory for reproducibility
    dest_script = os.path.join(work_dir, 'generate_scoring_model.py')
    try:
        shutil.copy(__file__, dest_script)
        print(f"Copied script to {dest_script}")
    except Exception as e:
        print(f"Note: Could not copy script to work_dir: {e}")
        
    # 6. Mandatory Validations
    print("\n=== RUNNING MANDATORY VALIDATIONS ===")
    num_semis = len(df_summary)
    num_detail_rows = len(df_detail)
    num_unique_skus = df_detail['Stone SKU'].nunique()
    
    print(f"1. Validation Counts:")
    print(f"   • Total Semi count: {num_semis}")
    print(f"   • Total detail rows: {num_detail_rows}")
    print(f"   • Total unique Stone SKUs: {num_unique_skus}")
    print(f"   • Composition conflicts between FGs: {num_conflicts}")
    
    # 2. Check 1 Semi = 1 Summary row
    assert num_semis == df_summary['SemiBOM'].nunique(), "ERROR: Duplicate SemiBOM in summary!"
    print("2. Verified: 1 Semi = exactly 1 summary row.")
    
    # 3. Check no duplicate SemiBOM + StoneSKU in detail
    dup_detail = df_detail.duplicated(subset=['SemiBOM', 'Stone SKU']).sum()
    assert dup_detail == 0, f"ERROR: Found {dup_detail} duplicate (SemiBOM, StoneSKU) in detail!"
    print("3. Verified: 0 duplicate (SemiBOM, StoneSKU) in detail after aggregation.")
    
    # 4. Check SUM EffectiveStoneCount detail = TotalStoneCount summary per Semi
    sum_detail = df_detail.groupby('SemiBOM')['Effective Stone Count'].sum()
    sum_summary = df_summary.set_index('SemiBOM')['Total Stone Count']
    diff_counts = (sum_detail != sum_summary).sum()
    assert diff_counts == 0, f"ERROR: Mismatch in total stone count for {diff_counts} Semis!"
    print("4. Verified: SUM(EffectiveStoneCount detail) == TotalStoneCount summary for all Semis.")
    
    # 5. Check exactly 11 sheets
    wb_test = openpyxl.load_workbook(output_file, read_only=True)
    sheet_names = wb_test.sheetnames
    expected_sheets = [
        "README", "Model Formula", "Rule Material", "Rule Gem Shape", "Rule Pearl Shape",
        "Rule Stone Count", "Rule Size Carat", "Rule Pearl mm", "Pending Setting",
        "Semi Summary", "Semi Stone Detail"
    ]
    print(f"5. Workbook Sheet Count: {len(sheet_names)}")
    print(f"   Sheets: {sheet_names}")
    assert sheet_names == expected_sheets, f"ERROR: Sheets mismatch! Expected {expected_sheets}, got {sheet_names}"
    print("5. Verified: Workbook contains all 11 required sheets in exact order.")
    
    # 6. File integrity test
    wb_test.close()
    print("6. Verified: Workbook loaded successfully without corruption.")
    
    # 7. Print Score Status Summary & Samples
    status_counts = df_summary['Score Status'].value_counts()
    print("\nScore Status Breakdown:")
    for st, c in status_counts.items():
        print(f"   • {st}: {c} ({c/num_semis*100:.1f}%)")
        
    print("\nSample Score Records:")
    sample_cols = [
        'SemiBOM', 'Stone Composition', 'Material Score', 'Shape Component',
        'Count Score', 'Size Component', 'Strict Stone Complexity',
        'Provisional Stone Complexity', 'Score Status'
    ]
    samples = df_summary.sample(5, random_state=42)[sample_cols]
    for idx, s in samples.iterrows():
        print("-" * 80)
        print(f"SemiBOM: {s['SemiBOM']}")
        print(f"Composition: {s['Stone Composition']}")
        print(f"Material Score: {s['Material Score']} | Shape Component: {s['Shape Component']} | Count Score: {s['Count Score']} | Size Component: {s['Size Component']}")
        print(f"Strict Complexity: {s['Strict Stone Complexity']} | Provisional Complexity: {s['Provisional Stone Complexity']} | Status: {s['Score Status']}")
    print("-" * 80)
    
    print("\n=== ALL PIPELINE STEPS AND VALIDATIONS COMPLETED SUCCESSFULLY! ===")

if __name__ == '__main__':
    main()

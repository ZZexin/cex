import fs from 'node:fs/promises';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';
import assert from 'node:assert/strict';
const dir=new URL('.',import.meta.url).pathname.replace(/^\/([A-Z]:)/i,'$1');
const rows=JSON.parse(await fs.readFile(dir+'/cycle_ranges.json','utf8'));
const wb=Workbook.create();
const sheet=wb.worksheets.add('循环电压电流范围');
const last=rows.length+7;
sheet.showGridLines=false;
sheet.getRange('A1:K'+last).format.font={name:'Arial',size:11,color:'#243444'};
sheet.getRange('A1:K'+last).format.verticalAlignment='center';
sheet.getRange('A1:K'+last).format.wrapText=true;
[65,100,510,75,85,115,115,120,120,100,150].forEach((w,i)=>sheet.getRangeByIndexes(0,i,last,1).format.columnWidthPx=w);
sheet.getRange('A1:K1').format.rowHeightPx=10;
sheet.getRange('A2').values=[['NDAX 各循环电压与电流范围']];
sheet.getRange('A2').format.font={size:16,bold:true,color:'#233D52'};
sheet.getRange('A2').format.wrapText=false;
sheet.getRange('A2:K2').format.rowHeightPx=34;
sheet.getRange('A2:K2').format.borders={bottom:{style:'thin',color:'#6B8FA5'}};
[
 '15 个文件，共 64 个循环。每圈分充电、放电两行，共 128 行。可按材料、文件名、循环号和阶段筛选。',
 '范围取原始记录最小值与最大值，包含工步切换及设定调整，不做平滑。电流单位 µA（1 µA = 0.001 mA），充电为正，放电为负。',
 '末点截止判据：充电 ≥ 1.7995 V，放电 ≤ 0.8005 V。无对应记录时数值留空。材料按文件名标注，重复导出保留，标签真实性待核实。'
].forEach((s,i)=>{
sheet.getRange('A'+(i+3)).values=[[s]];
sheet.getRange('A'+(i+3)).format.wrapText=false;
sheet.getRange('A'+(i+3)).format.font={size:10,color:'#536374'};
sheet.getRange('A'+(i+3)+':K'+(i+3)).format.rowHeightPx=25;
});
sheet.getRange('A6:K6').format.rowHeightPx=12;
const matrix=rows.map(r=>[r.id,r.material,r.filename,r.cycle,r.phase,r.vmin,r.vmax,r.imin,r.imax,r.n,r.status]);
sheet.getRange('A7:K7').values=[['文件编号','材料\n（按文件名）','完整文件名','循环号','阶段','最低电压\n(V)','最高电压\n(V)','最小电流\n(µA)','最大电流\n(µA)','记录数','末点状态']];
sheet.getRange('A8:K'+last).values=matrix;
const table=sheet.tables.add('A7:K'+last,true,'CycleVoltageCurrentRanges');
table.showFilterButton=true;
sheet.getRange('A7:K7').format.fill='#233D52';
sheet.getRange('A7:K7').format.font={name:'Arial',size:11,bold:true,color:'#FFFFFF'};
sheet.getRange('A7:K7').format.horizontalAlignment='center';
sheet.getRange('A7:K7').format.rowHeightPx=52;
sheet.getRange('A8:K'+last).format.rowHeightPx=56;
sheet.getRange('C8:C'+last).format.font={name:'Arial',size:10,color:'#243444'};
sheet.getRange('A8:A'+last).setNumberFormat('00');
sheet.getRange('F8:G'+last).setNumberFormat('0.0000');
sheet.getRange('H8:I'+last).setNumberFormat('0.00');
sheet.getRange('J8:J'+last).setNumberFormat('0');
sheet.getRange('K8:K'+last).conditionalFormats.add('containsText',{text:'未达截止',format:{font:{color:'#9A5519'}}});
sheet.getRange('K8:K'+last).conditionalFormats.add('containsText',{text:'无对应记录',format:{font:{color:'#9A5519'}}});
sheet.freezePanes.freezeRows(7);
sheet.freezePanes.freezeColumns(2);
await wb.recalculate();
assert.equal(rows.length,128);
assert.equal(new Set(rows.map(r=>r.id+':'+r.cycle)).size,64);
assert.equal(new Set(rows.map(r=>r.filename)).size,15);
assert.equal(rows.filter(r=>r.n===0).length,2);
assert.deepEqual(sheet.getRange('A8:K'+last).values,matrix);
for (const r of rows) {
 if(r.n===0){assert.equal(r.vmin,null);assert.equal(r.imax,null);}
 else {assert.ok(r.vmin<=r.vmax);assert.ok(r.imin<=r.imax);assert.ok(r.phase==='充电'?r.imin>0:r.imax<0);}
}
console.log((await wb.inspect({kind:'region',sheetId:sheet.name,range:'D26:K31',maxChars:1600,tableMaxRows:6,tableMaxCols:8})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'Error scan'})).ndjson);
for(const [range,name] of [['A1:K15','ranges_top'],['A76:K84','ranges_material_transition'],['A128:K135','ranges_end']]){
const preview=await wb.render({sheetName:sheet.name,range,scale:1,format:'png'});
await fs.writeFile(dir+'/'+name+'.png',new Uint8Array(await preview.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(dir+'/NDAX_各循环电压电流范围.xlsx');
console.log('Verified 15 files, 64 cycles, 128 phase rows. All original records assigned to charge/discharge ranges. Two missing discharge phases retained.');

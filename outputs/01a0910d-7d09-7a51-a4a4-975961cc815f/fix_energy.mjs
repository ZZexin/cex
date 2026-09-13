import fs from 'node:fs/promises';
import {FileBlob, SpreadsheetFile} from '@oai/artifact-tool';
const source='C:/Users/Zexin/Downloads/sno2zmo, 0.05ma,cm2dcg. DARK _27.0.0.1-BTS82-45-11-1-2818575313/sno2zmo/Selected/SNO2ZMO_10_G2.xlsx';
const dir='C:/Users/Zexin/Documents/cex/outputs/01a0910d-7d09-7a51-a4a4-975961cc815f';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const sheet=wb.worksheets.getItem('SNO2ZMO_10_G2');
console.log((await wb.inspect({kind:'table',range:'SNO2ZMO_10_G2!L1:N5',include:'values,formulas',tableMaxRows:5,tableMaxCols:3,maxChars:2500})).ndjson);
const preview=async name=>{
 const img=await wb.render({sheetName:sheet.name,range:'L1:N7',scale:1.5,format:'png'});
 await fs.writeFile(`${dir}/${name}.png`,new Uint8Array(await img.arrayBuffer()));
};
if(process.argv[2]!=='edit'){await preview('energy_before');process.exit(0);}
const formulas=[];
for(let r=3;r<=5499;r++) formulas.push([`=IF(OR(B${r}<>B${r-1},D${r}<>D${r-1},E${r}<>E${r-1}),0,N${r-1}+(H${r-1}+H${r})/2*(M${r}-M${r-1}))`]);
sheet.getRange('N3:N5499').formulas=formulas;
sheet.getRange('N748').values=[[0]];
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'SNO2ZMO_10_G2!M747:N750',include:'values,formulas',tableMaxRows:4,tableMaxCols:2,maxChars:2500})).ndjson);
const vals=sheet.getRange('N2:N5499').values;
if(vals.some(row=>typeof row[0]!=='number'||!Number.isFinite(row[0])||row[0]<0)) throw new Error('Invalid calculated energy');
console.log('endpoints',vals[745],vals.at(-1));
await preview('energy_after');
await (await SpreadsheetFile.exportXlsx(wb)).save(`${dir}/energy_artifact_intermediate.xlsx`);
console.log('EXPORTED');

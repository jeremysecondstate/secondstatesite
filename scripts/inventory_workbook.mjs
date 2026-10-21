/** Append researched auction purchases to the established SUPREME inventory.
 * Usage: bundled node inventory_workbook.mjs --records private.json
 *   --workbook <absolute.xlsx> --output-dir <private directory> [--apply]
 * Sources and personal data belong in ignored private_data, never in this file.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const require = createRequire(import.meta.url);
const argv = process.argv.slice(2);
const opt = (name) => { const i = argv.indexOf(name); return i < 0 ? null : argv[i + 1]; };
const source = opt('--workbook') || process.env.INVENTORY_WORKBOOK_PATH;
const recordsPath = opt('--records');
const outputDir = path.resolve(opt('--output-dir') || path.join('private_data', 'inventory', crypto.randomUUID()));
const apply = argv.includes('--apply');
if (!source || !recordsPath || !path.isAbsolute(source)) throw new Error('Provide --workbook absolute.xlsx and --records private.json.');
const runtime = process.env.CODEX_ARTIFACT_RUNTIME || path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies');
const dependencies = path.join(runtime, 'node', 'node_modules');
const python = process.env.CODEX_ARTIFACT_PYTHON || path.join(runtime, 'python', process.platform === 'win32' ? 'python.exe' : 'bin/python');
const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool', { paths: [dependencies] })).href);
const packageHelper = fileURLToPath(new URL('./inventory_xlsx_package.py', import.meta.url));
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const safeText = value => typeof value === 'string' && value.startsWith('=') ? "'" + value : value;
const costFields=['shipping_cost','shipping_paid_jeremy','shipping_paid_alex','shipping_paid_oliver','restoration_cost','restoration_paid_jeremy','restoration_paid_alex','restoration_paid_oliver'];
const finiteOrNull = (value, name) => {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw new Error(`Invalid numeric field ${name}.`);
  return value;
};
const input = JSON.parse(await fs.readFile(recordsPath, 'utf8'));
if (!Array.isArray(input.lots) || !input.lots.length || input.lots.length > 100) throw new Error('Expected 1–100 researched lots.');
for (const lot of input.lots) {
  for (const key of ['lot_url', 'auction_house', 'sale_date', 'lot_number', 'artist', 'title']) {
    if (typeof lot[key] !== 'string' || !lot[key].trim()) throw new Error(`Missing ${key}.`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(lot.sale_date) || Number.isNaN(Date.parse(lot.sale_date)) || new Date(lot.sale_date).toISOString().slice(0,10)!==lot.sale_date) throw new Error('Invalid sale_date.');
  if (!/^https:\/\//.test(lot.lot_url)) throw new Error('Lot URL must be HTTPS.');
  for (const key of ['height_in', 'width_in', 'hammer_price_usd', 'premium_total_usd', 'buyer_premium_rate', 'appraised_low', 'appraised_high', 'asking_price','original_currency_amount',...costFields]) finiteOrNull(lot[key], key);
  if (lot.buyer_premium_rate != null && (!lot.premium_source_url || lot.buyer_premium_rate > 1)) throw new Error('Derived hammer requires a supported premium rate and source.');
}
await fs.mkdir(outputDir, { recursive: true });
const planPath = path.join(outputDir, 'workbook-plan.json');
const planSummary = execFileSync(python, [packageHelper, 'inspect', '--source', source, '--records', path.resolve(recordsPath), '--plan', planPath], {encoding:'utf8'});
const plan = JSON.parse(await fs.readFile(planPath, 'utf8'));
if (!plan.count) {
  const receipt = {status:'already_recorded', workbook:source, sheet:plan.sheet, entries:plan.skipped, sha256:plan.sha256};
  await fs.writeFile(path.join(outputDir, 'workbook-receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
  process.exit(0);
}
const lockPath = source + '.inventory.lock';
let lock;
try {
  lock = await fs.open(lockPath, 'wx');
  await lock.writeFile(JSON.stringify({pid:process.pid, started_at:new Date().toISOString()}));
  const excelLock = path.join(path.dirname(source), '~$' + path.basename(source));
  if (await fs.stat(excelLock).then(()=>true,()=>false)) throw new Error('Workbook is open in Excel. Close it before updating.');
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
  const sheet = workbook.worksheets.getItem(plan.sheet);
  const at = plan.insert_at, n = plan.count;
  const shift = address => address.replace(/(\$?[A-Z]{1,3})(\$?)(\d+)/g, (_, col, abs, row) => col+abs+(Number(row)>=at ? Number(row)+n : row));
  const previewBefore = await workbook.render({sheetName:plan.sheet,range:`C${Math.max(4,at-3)}:L${at+1}`,scale:1,format:'png'});
  await fs.writeFile(path.join(outputDir,'before.png'), new Uint8Array(await previewBefore.arrayBuffer()));
  const movedMerges = plan.merges.filter(m => shift(m) !== m);
  for (const merge of movedMerges) sheet.unmergeCells(merge);
  for (let row = plan.last_row; row >= at; row--) {
    sheet.getRange(`A${row+n}:AE${row+n}`).copyFrom(sheet.getRange(`A${row}:AE${row}`), 'all');
    if (plan.row_heights[row]) sheet.getRange(`A${row+n}:AE${row+n}`).format.rowHeight = Number(plan.row_heights[row]);
  }
  sheet.getRange(`A${at}:AE${at+n-1}`).clear({applyTo:'all'});
  for (const merge of movedMerges) sheet.mergeCells(shift(merge));
  const rows = [];
  for (let i=0;i<n;i++) {
    const lot = plan.lots[i], row = at+i;
    sheet.getRange(`A${row}:AC${row}`).copyFrom(sheet.getRange(`A${at-1}:AC${at-1}`),'all');
    const priceNote = lot.hammer_price_usd == null && lot.premium_total_usd != null && lot.buyer_premium_rate != null
      ? `Hammer calculated from ${lot.auction_house}'s published premium-inclusive result at ${Number((lot.buyer_premium_rate*100).toFixed(4))}% buyer premium (${lot.premium_source_url}); reconcile to invoice.`
      : 'Purchase amounts require invoice reconciliation.';
    const estimateNote = lot.estimate_low != null && lot.estimate_high != null ? `Auction estimate: USD ${lot.estimate_low}–${lot.estimate_high}; this is not an appraisal.` : '';
    const pending=[];
    if(lot.shipping_cost==null) pending.push('shipping cost');
    if(costFields.slice(1,4).some(key=>lot[key]==null)) pending.push('shipping payer allocations');
    if(lot.restoration_cost==null) pending.push('restoration cost');
    if(costFields.slice(5,8).some(key=>lot[key]==null)) pending.push('restoration payer allocations');
    if(lot.appraised_low==null || lot.appraised_high==null) pending.push('appraisal');
    if(lot.asking_price==null) pending.push('asking price');
    if(!lot.location || lot.location==='Unconfirmed') pending.push('current location');
    const notes = [lot.description, `${lot.dimension_basis || 'Print'} dimensions shown in Height/Width.`, priceNote, estimateNote,
      pending.length?`Pending: ${pending.join(', ')}. Blank cost fields are unknown, not zero.`:'',lot.provided_facts_source?`Additional source: ${lot.provided_facts_source}`:'',
      `Source: ${lot.lot_url}`, `Inventory key: ${lot.auction_house} | ${lot.sale_date} | ${lot.lot_number}`].filter(Boolean).join('\n');
    const values = [plan.last_inventory_number+i+1,lot.image_url?'Img':null,lot.catalog_number||'Not supplied',lot.artist,lot.title,lot.year??'Not supplied',lot.medium||'Not supplied',lot.height_in??null,lot.width_in??null,
      lot.hammer_price_usd??null,lot.original_currency_amount??null,lot.premium_total_usd??null,notes,new Date(lot.sale_date+'T00:00:00Z'),lot.auction_house,
      ...costFields.map(key=>lot[key]??null),lot.appraised_low??null,lot.appraised_high??null,lot.asking_price??null,lot.status||'Purchased',lot.location||'Unconfirmed',lot.listing_info||'Research pending.'];
    sheet.getRange(`A${row}:AC${row}`).values=[values.map(safeText)];
    // Artifact Tool cannot calculate HYPERLINK; the package adapter adds native
    // hyperlink metadata to these Artifact-authored display values instead.
    if (lot.hammer_price_usd == null && lot.premium_total_usd != null && lot.buyer_premium_rate != null) sheet.getRange(`J${row}`).formulas=[[`=ROUND(L${row}/(1+${lot.buyer_premium_rate}),2)`]];
    sheet.getRange(`A${row}:AC${row}`).format.rowHeight=210;
    sheet.getRange(`N${row}`).setNumberFormat('mm/dd/yy');
    rows.push({lot_url:lot.lot_url,row,inventory_number:plan.last_inventory_number+i+1});
  }
  for (const item of plan.formulas) workbook.worksheets.getItem(item.sheet).getRange(item.address).formulas=[[item.formula]];
  workbook.recalculate();
  const check = await workbook.inspect({kind:'table',range:`'${plan.sheet}'!A${at}:AC${at+n-1}`,include:'values,formulas',tableMaxRows:n,tableMaxCols:29,maxChars:18000});
  await fs.writeFile(path.join(outputDir,'inspection.ndjson'),check.ndjson);
  const errors = await workbook.inspect({kind:'match',range:`'${plan.sheet}'!A${at}:AC${at+n-1}`,searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:50},maxChars:3000});
  await fs.writeFile(path.join(outputDir,'formula-check.ndjson'),errors.ndjson);
  if (/#REF!|#DIV\/0!|#VALUE!|#NAME\?|#NUM!|#NULL!/.test(errors.ndjson.replace(/"searchTerm":"[^"]*"/g,''))) throw new Error('Formula errors in newly authored inventory rows.');
  const authored = path.join(outputDir,'authored.xlsx');
  await (await SpreadsheetFile.exportXlsx(workbook)).save(authored);
  const candidate = path.join(outputDir,'candidate.xlsx');
  const packageResult = JSON.parse(execFileSync(python,[packageHelper,'preserve','--source',source,'--authored',authored,'--plan',planPath,'--output',candidate],{encoding:'utf8'}));
  const final = await SpreadsheetFile.importXlsx(await FileBlob.load(candidate));
  final.recalculate();
  for (const [label,range] of [['artwork',`C${at}:L${at+n-1}`],['notes',`M${at}:O${at+n-1}`],['status',`X${at}:AC${at+n-1}`]]) {
    const preview = await final.render({sheetName:plan.sheet,range,scale:1,format:'png'});
    await fs.writeFile(path.join(outputDir,label+'.png'),new Uint8Array(await preview.arrayBuffer()));
  }
  const receipt={status:apply?'updated':'prepared',workbook:source,sheet:plan.sheet,entries:rows,skipped:plan.skipped,sha256:packageResult.sha256,changed_members:packageResult.changed_members};
  if (apply) {
    if (digest(await fs.readFile(source)) !== plan.sha256) throw new Error('Workbook changed before replacement; retry against current version.');
    if (await fs.stat(excelLock).then(()=>true,()=>false)) throw new Error('Workbook was opened in Excel during preparation. Close it and retry.');
    const backup = path.join(outputDir,'SUPREME.before.xlsx');
    await fs.copyFile(source,backup,fs.constants.COPYFILE_EXCL);
    const temporary = path.join(path.dirname(source),'.'+path.basename(source)+'.'+crypto.randomUUID()+'.tmp');
    await fs.copyFile(candidate,temporary,fs.constants.COPYFILE_EXCL);
    if (digest(await fs.readFile(source)) !== plan.sha256 || await fs.stat(excelLock).then(()=>true,()=>false)) { await fs.unlink(temporary); throw new Error('Workbook changed or was opened in Excel while staging replacement.'); }
    await fs.rename(temporary,source);
    if (digest(await fs.readFile(source)) !== receipt.sha256) throw new Error('Saved workbook hash verification failed.');
    receipt.backup=backup;
  }
  await fs.writeFile(path.join(outputDir,'workbook-receipt.json'),JSON.stringify(receipt,null,2));
  console.log(JSON.stringify(receipt));
} finally {
  if (lock) { await lock.close(); await fs.unlink(lockPath); }
}

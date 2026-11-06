// Import aggregate reports explicitly for publication on the public dashboard.
const fs=require('fs'), path=require('path');
const R=require('../mhi/readiness.js');
const destination=path.resolve(__dirname,'../data/release_reports.json');
function ingest(file) {
  const raw=JSON.parse(fs.readFileSync(file,'utf8'));
  if(!Array.isArray(raw)||raw.length>500)throw Error('Expected at most 500 aggregate reports.');
  const incoming=raw.map(r=>R.validate(r));
  const existing=fs.existsSync(destination)?JSON.parse(fs.readFileSync(destination,'utf8')).map(r=>R.validate(r)):[];
  const merged=new Map([...existing,...incoming].map(r=>[JSON.stringify([r.profile,r.end,r.query,r.filters,r.marketplace,r.currency]),r]));
  fs.writeFileSync(destination+'.tmp',JSON.stringify([...merged.values()],null,2)+'\n');
  fs.renameSync(destination+'.tmp',destination);
  return incoming.length;
}
if(require.main===module) {
  if(!process.argv[2]){console.error('Usage: node scripts/import_release_reports.cjs saved-reports.json');process.exit(1);}
  try{console.log(`Imported ${ingest(process.argv[2])} aggregate reports. Rebuild before publishing.`);}
  catch(e){console.error(e.message);process.exit(1);}
}
module.exports={ingest};

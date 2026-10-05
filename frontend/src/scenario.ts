// Integer cents keep scenario arithmetic independent of floating point rounding.
const cents=(v:string):bigint=>{const match=String(v).match(/^(-?)(\d+)(?:\.(\d+))?$/);if(!match)throw new Error('金额无效');const fraction=(match[3]||'').padEnd(3,'0');const result=BigInt(match[2])*100n+BigInt(fraction.slice(0,2))+(Number(fraction[2])>=5?1n:0n);return match[1]?-result:result;};
export function scenarioLoss(snapshot:any,drop:number,fxDrop:number):string|null{
 if(!snapshot?.complete||!Number.isInteger(drop)||!Number.isInteger(fxDrop)||drop<0||drop>100||fxDrop<0||fxDrop>100)return null;
 try{let loss=0n;for(const p of snapshot.positions||[]){if(p.base_value==null)return null;const value=cents(p.base_value),remaining=BigInt(100-drop)*BigInt(p.currency==='HKD'?100-fxDrop:100);loss+=(value*(10000n-remaining)+5000n)/10000n;}
 for(const c of snapshot.cash||[]){if(c.currency==='HKD'){if(c.base_value==null)return null;loss+=(cents(c.base_value)*BigInt(fxDrop)+50n)/100n;}}
 return `${loss/100n}.${String(loss%100n).padStart(2,'0')}`;
 }catch{return null;}
}

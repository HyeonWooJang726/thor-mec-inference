#include <cstdint>
#include <algorithm>
extern "C" void pair_count(const int64_t* w, int64_t nw, const int64_t* s, int64_t ns, const int64_t* budgets, int64_t nb, uint64_t* result) {
 for(int64_t k=0;k<nb;k++) {
  const int64_t b=budgets[k]; uint64_t count=0;
  if(!nw || !ns || w[0]+s[0]>b){result[k]=0;continue;}
  if(w[nw-1]+s[ns-1]<=b){result[k]=(uint64_t)nw*ns;continue;}
  int64_t wi=std::upper_bound(w,w+nw,b-s[0])-w;
  int64_t sj=std::upper_bound(s,s+ns,b-w[0])-s;
  // Exact monotone pair count, all empirical observations retained.
  for(int64_t i=0;i<wi;i++) {
   while(sj>0 && w[i]+s[sj-1]>b) --sj;
   if(!sj)break;
   count+=(uint64_t)sj;
  }
  result[k]=count;
 }
}

`timescale 1ns/1ps
module tb;
reg clk=0, rst=1, start=0, valid_in=0;
reg [127:0] data_in=0,key_in=0;
wire [127:0] data_out;
wire valid_out,done;
TopModule dut(.clk(clk),.rst(rst),.start(start),.mode(1'b0),.valid_in(valid_in),
 .data_in(data_in),.key_in(key_in),.data_out(data_out),.valid_out(valid_out),.done(done));
always #5 clk=~clk;
reg [127:0] pt[0:63],ky[0:63],expected[0:63];
integer errors=0,samples=0,sent=0,received=0,cycles=0,i;
integer last_received_cycle=-1;
always @(posedge clk) begin
 #1;
 cycles=cycles+1;
 if (rst) begin
   if (valid_out !== 0 || done !== 0) errors=errors+1;
 end else if (valid_out === 1) begin
   samples=samples+1;
   if (received>=sent || received>=64) errors=errors+1;
   else if (data_out !== expected[received] || done !== 1) errors=errors+1;
   // 前32个输入连续发送，流水线填满后必须每拍输出。
   if (received>0 && received<32 && cycles != last_received_cycle+1) errors=errors+1;
   last_received_cycle=cycles;
   received=received+1;
 end else if (valid_out !== 0) errors=errors+1;
end
initial begin
pt[0]=128'h00112233445566778899aabbccddeeff; ky[0]=128'h000102030405060708090a0b0c0d0e0f; expected[0]=128'h69c4e0d86a7b0430d8cdb78070b4c55a;
pt[1]=128'h00000000000000000000000000000000; ky[1]=128'h00000000000000000000000000000000; expected[1]=128'h66e94bd4ef8a2c3b884cfa59ca342b2e;
pt[2]=128'hffffffffffffffffffffffffffffffff; ky[2]=128'hffffffffffffffffffffffffffffffff; expected[2]=128'hbcbf217cb280cf30b2517052193ab979;
pt[3]=128'h00000000000000000000000000000000; ky[3]=128'hffffffffffffffffffffffffffffffff; expected[3]=128'ha1f6258c877d5fcd8964484538bfc92c;
pt[4]=128'hffffffffffffffffffffffffffffffff; ky[4]=128'h00000000000000000000000000000000; expected[4]=128'h3f5b8cc9ea855a0afa7347d23e8d664e;
pt[5]=128'he39a48aaa213ee9e6de04edfd96f639f; ky[5]=128'ha9634841b5673ae319fe068ec977a27d; expected[5]=128'h58829913e85a65628f2691cb91674081;
pt[6]=128'h452252f20e04cdb33f1bd613b242dee0; ky[6]=128'h1bfd944d0749e21cf4071ff4c6ae8784; expected[6]=128'heb329b88b41d1dabb825d147c2aacb2d;
pt[7]=128'h0ff3dced9237b2937d0ba64cee007a81; ky[7]=128'hfcc941786a3c3a42695f132f1802789a; expected[7]=128'h0d0e4a3c00c1560575d0e015e3fe0697;
pt[8]=128'h804e84382069a137def2ac272a7beca0; ky[8]=128'h0db162a9986cd8d6bad3151332452cd8; expected[8]=128'h4282191f5276b8bf5193eaee87f14e74;
pt[9]=128'ha6638e96a4b90f47a2156f229ec200f7; ky[9]=128'h5758285edb962a130ba91a087ef8e5d7; expected[9]=128'h4b5d813ecd53efecd980f9ba38eaeb64;
pt[10]=128'he3f2c927363a0ed4732825218503be3e; ky[10]=128'ha62376c6d373ea783d9776486b855a36; expected[10]=128'h0950097b9179d5ae7a6d8f624b7ebb37;
pt[11]=128'hbb8f217cc9379b3d752e52be8f10a8c0; ky[11]=128'hf5f92d744d500aa32ed811dce068f864; expected[11]=128'h1cd6062f7b9567a305bc736617bef7ee;
pt[12]=128'h77c2b01f8bfd27c63b78015ad9d70990; ky[12]=128'h406c6948b68a841261491fa4885e434c; expected[12]=128'h7088ee08758ceb95af48ecaf5bf9e578;
pt[13]=128'ha89b6d50994d57e418f5ccbb0c422fec; ky[13]=128'he4f718094dc724de58332d3bce5afcc1; expected[13]=128'h6cce2ab4e8249c5b74ee7e53ee3c3787;
pt[14]=128'hd16a3f3ae911d64d22259b3c89ba2c06; ky[14]=128'he2af57a962ea88fbe4be5e3b7ccd28fe; expected[14]=128'h09a9034946a023d789840e952d53c435;
pt[15]=128'ha134e05d21759d33ffda8f9054b5b59f; ky[15]=128'h7750cd88a1265aa364a096f58958ebb2; expected[15]=128'hbd34d4e60f36b7c9f303d9e4d760a9b2;
pt[16]=128'hd787d6e4d61e9806b49c64301fdcf695; ky[16]=128'h556e119bfe59eeb0ae7c326269acd425; expected[16]=128'ha98869f6b7ff6bafd56d1d8b8e7f632f;
pt[17]=128'ha719ed4e30a9fb3250df9e8ecb808c0c; ky[17]=128'h939606d961f62f816aaf6fd5acedf2f6; expected[17]=128'h8d183d02ec04e92b846de901dbdb9597;
pt[18]=128'h79da839e4ee37768ee91bbe68f4e54a9; ky[18]=128'h71f5ae9d14fd45f59a8d11dea6b215e6; expected[18]=128'h045cc2cd5574cfec558148100d34bc7c;
pt[19]=128'hb83b150dfefb8782b47566d577c9594a; ky[19]=128'hbed01160faf06d254de47e1bddc0732f; expected[19]=128'h37f287493eaaafa5b10b61caee6985bc;
pt[20]=128'h53ad5e6a14351a1a851ed3dc60f1f2c6; ky[20]=128'h4fc8418fd4284116c2bca96f720193c3; expected[20]=128'h1908f382671f441e01f9ca1e415a512f;
pt[21]=128'h5fc1622f2c468406734a626556d664d1; ky[21]=128'h1e826b84bf214b4248918b9c0ef92214; expected[21]=128'hcd831374df2170bb0d4ad4bef1b9a04d;
pt[22]=128'h5f0afbec03331de9acbf8fed6b8c8618; ky[22]=128'h04ca38f441cec82dc999e36b3f093558; expected[22]=128'hd957404d536612ea6dcfe6406da4002a;
pt[23]=128'h071600bd46ef6c56924e40305a643d80; ky[23]=128'hfa6382aa3317585d73506eeb2d426cc9; expected[23]=128'he83af458f640504600f7a71d149c1bca;
pt[24]=128'h66ac9c04b7e8b92f3e4777995a107d33; ky[24]=128'h1a2329316b828849c901313a36eaff14; expected[24]=128'h874c656d1431e7130c5d41935e881e87;
pt[25]=128'h85150e7dce46712454f43e5f0b3faac6; ky[25]=128'h9ddb8c5fdc5d04bf539a4dc002947d6a; expected[25]=128'hbaf107dd2a93e523d0023081b45e1fdb;
pt[26]=128'h0689cc36847e3a85eb9fa595d100f872; ky[26]=128'h59f8ad39ce9b6d9e99a2f0fb2aafa4c7; expected[26]=128'h00e89a89b209b45696d93e4b39c20b73;
pt[27]=128'hd6c5341d6d31680dc1efb3ddb957767e; ky[27]=128'hd3f5d4370f394aa4a41f2c201392665d; expected[27]=128'h8a6952ed31e14e7b2eaf53197c5e271b;
pt[28]=128'h7492e6148c5d48abf9c44a4ede88cb79; ky[28]=128'h232f0f8902feff7f2d8d481c9b452040; expected[28]=128'h426bc2aaa8cd367226f00c6d50c3835f;
pt[29]=128'h20c954bab73fb14faeef1ce8c2fd4286; ky[29]=128'hd9702d4694fe1d0b08c905cce14f397e; expected[29]=128'h49c6947aced984849012a3777ff48971;
pt[30]=128'h4c2aceb231cdde9287fd8d7e32bcd029; ky[30]=128'h5af8dc30966097f5000c78fd53f248f2; expected[30]=128'h298ecb0fd0530315b535561b00fc1763;
pt[31]=128'hfd00cd554c5334e98b52a8553d8c54e8; ky[31]=128'hec1e179ad0468119e0e7ed888b9f1f76; expected[31]=128'h9c7a870c06a0afb909c77035424fbfd3;
pt[32]=128'h5c31f1ff4278fd80a25460d923096f7a; ky[32]=128'h49a9e114e96b285b754fa5a38916adcc; expected[32]=128'h3ca8d4d4d860cbc0f3952e570a9a9a16;
pt[33]=128'h204a20e87193aac1ab1572fb59db91fb; ky[33]=128'he0652f158d1fdb94857c1e3a01fb76bb; expected[33]=128'h1d69ea02782963d28de37a55d9dd081d;
pt[34]=128'h8d958ab6e49f43c44186521d1ffe39e5; ky[34]=128'h2ca2e079546ff589a8911d77ddddc295; expected[34]=128'h01bdbd9c3db02c927a854ddaa5ba88a1;
pt[35]=128'h993c7aea207c897866a77e06455a24b4; ky[35]=128'hea8574fee3fd334807a44bc37b88e07c; expected[35]=128'h36587009d2603ad76c4fe9cf7777d2f0;
pt[36]=128'h2ac0d426ef32f091d40daecf94c21b96; ky[36]=128'h163dd4304f58efae27112a209f5541c4; expected[36]=128'hc4fbf95670c9aa771c899b96c41225be;
pt[37]=128'hcc42b10286aac923eb2aac5c04e9f66b; ky[37]=128'h02eb1a01ac7c1e53badb5dc758e53ca3; expected[37]=128'ha9fba88c0c9fc6d935edce3dfc5b6839;
pt[38]=128'h785b0d2798df63ff93ee31d174dfe43e; ky[38]=128'h6fc9876b6428f56117a18339e035e67d; expected[38]=128'hc222e5f825472d6f720bb1734018c593;
pt[39]=128'h8d960a0a1345562d3ae94d373106a041; ky[39]=128'hfbd0bb8db62a451ba281d3ea91af3c90; expected[39]=128'ha8431adf51ed29015e0a742c5be58bda;
pt[40]=128'h7bee99c689ef14bde98c6379b1d2a7b7; ky[40]=128'ha2b3753e3f708eedaa938d766310e47c; expected[40]=128'hdd3563cb26c48a5bf9f65367f4b83b0e;
pt[41]=128'h5dac1050164dc15ad4cf26abe34b3fc4; ky[41]=128'h27f9b75f71f983cab6776eabe5c1a626; expected[41]=128'h2a3846f9ed12cdc656b60f4fef8f7efd;
pt[42]=128'h97f0a049fe2ee67ebbe35b2084ffec54; ky[42]=128'he45f56268df2f30927b96f924d41030f; expected[42]=128'h4c62d06de9e86fab8e3fdd3271b93661;
pt[43]=128'hd7180c1d3f39ed7727e65c346d47317f; ky[43]=128'h4f2157f43e49da7a67358bfab0d8db3f; expected[43]=128'ha72a1764f4150557a4d8a80256c1d105;
pt[44]=128'h266eabedc128469e3517016afbe5e917; ky[44]=128'h21741a2d7e314a748bb13f7a5cce35b4; expected[44]=128'habfc8f3b5741ccede4fa8ef304d3b417;
pt[45]=128'ha87d37f842efd4cf1f2885785d446b8d; ky[45]=128'hea03069cdab69bc9efebb3a53bf695e5; expected[45]=128'h4159edc0e9f32c8c61cb492de95e05c4;
pt[46]=128'h88df8c33a416695649e358e027b25034; ky[46]=128'hcd547939423a578ede1901d1e43d9f9f; expected[46]=128'hcfca483ccc85766dd0bbad87c4452862;
pt[47]=128'h8393bd3aff5d9a6f9d8bcc5243de426a; ky[47]=128'h6636b0311d32b8660faf368b2e6c53f6; expected[47]=128'h01e1f3738687dbdcd9eb2bd0eb42536e;
pt[48]=128'ha3cd5827eae8e7fca09c0d44fc8f4ef9; ky[48]=128'h650a7cd90a70c27027e4ae9f3d60ad26; expected[48]=128'h9ac932020e819493ef5fffd52d9ba60b;
pt[49]=128'h79e1203666b891b85c1594e7a3aec968; ky[49]=128'hb68b8be2faac77d1475b1e0bc41d798a; expected[49]=128'h5f6556f2b36aa82163d92064c4f6e5f0;
pt[50]=128'h7e5b3d7c3a72749443d86e30a1e4a913; ky[50]=128'h1b93e3ee6c6d1a61e50d8be12c036a16; expected[50]=128'heefaf7828dcf19b21c934f0715299ef3;
pt[51]=128'h2c36486166e27a0acc5aec1007de0cf2; ky[51]=128'h67ac08c06b23bdf3b1ee7aed2568ed9f; expected[51]=128'h12c01eee970e67cc6f67a59ddde8212d;
pt[52]=128'h73a9f80ba7696735a466fb928dcda364; ky[52]=128'hdcdc764f4a6811355e6433a7949dc3ac; expected[52]=128'hbf4aa781cad07adad645dbe6a3f4a69d;
pt[53]=128'hfc25cfdedca28930c78679767928985c; ky[53]=128'hbd32477c18c6faf5e46b2dbb3e35fbfb; expected[53]=128'h821ddbca0fca061708082161194af766;
pt[54]=128'hb387de795a4f620df1d4baeeb9aa6216; ky[54]=128'h0ffded251b9341017370761059a3d48e; expected[54]=128'h9999d3e46b2e32d09345071f114f1d72;
pt[55]=128'h69dafca443a3d66d6e371cdd9252e80d; ky[55]=128'he58a2e0798093740c710eeca4ea4c745; expected[55]=128'h113bca2b989cb2e9f6129aef75f46afa;
pt[56]=128'hdb4f8a05c33b2679ec3512ab0cbfcb17; ky[56]=128'h88855f357e9876dad1f00e3dc57d4f12; expected[56]=128'h0165313b5e277899f585bb6912388b68;
pt[57]=128'hc2e32cef1778677b76e27ef5b00ce2b1; ky[57]=128'hf1a0259670ca55638d83f27ed996ee43; expected[57]=128'h8d658124b8eafccc2154e908beb42218;
pt[58]=128'hb7c2caccaf3c81518c4bc6c081a24357; ky[58]=128'hd580e654794316932bf3770d54a6bc64; expected[58]=128'hfa44004bbf63e2bb3c4ed54eda674876;
pt[59]=128'h9f4914d5b38ea02251310f0ac9705d9c; ky[59]=128'hec2d487dbd3d7350d168d9769b7bd3a5; expected[59]=128'h58d082d3f9a1e061829dd26cce3e7008;
pt[60]=128'h69ebaedef2af6817a52b2ee93dfa86c6; ky[60]=128'h097e6395dc566375a8d956b61f7c9e5b; expected[60]=128'hf3e5c2f38dd9333216c0ab1c433a6b0e;
pt[61]=128'h639a9d5666d832a88ea5052edd677298; ky[61]=128'hed09c496c559603d991dd8fddf080258; expected[61]=128'h9fc26dd43e9af62a380ba1f740bf3c60;
pt[62]=128'h313d698833cefa70864e7ffc1933d92d; ky[62]=128'h12163d9457cd4241e6dd0d22a47751ac; expected[62]=128'hed2b2d8379af09bb83110363b599ca2c;
pt[63]=128'h1d5cac687771ce41bd660036a2c72757; ky[63]=128'hb313d4ddbd801f6fe93c8f51107d4e76; expected[63]=128'he1c54796a7dde4ef23e8c94e6e3ace4e;
 repeat(3) @(negedge clk);
 rst=0;
 for(i=0;i<64;i=i+1) begin
   @(negedge clk);
   data_in=pt[i];key_in=ky[i];start=1;valid_in=1;sent=sent+1;
   if(i>=32 && i%3==0) begin @(negedge clk);start=0;valid_in=0; end
 end
 @(negedge clk);start=0;valid_in=0;
 repeat(100) @(negedge clk);
 if(received!=64) errors=errors+1;
 rst=1;
 repeat(3) @(negedge clk);
 $display("Mismatches: %0d in %0d samples",errors,samples);
 $finish;
end
initial begin #100000; $display("TIMEOUT"); $finish; end
endmodule

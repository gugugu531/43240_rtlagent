`timescale 1ns/1ps
module tb;
reg clock=0,reset=1;
reg [7:0] lfsr_seed=1,expected;
wire [7:0] lfsr_out;
TopModule dut(.clock(clock),.reset(reset),.lfsr_seed(lfsr_seed),.lfsr_out(lfsr_out));
always #5 clock=~clock;
integer errors=0,samples=0,s,j;
reg [255:0] seen;
initial begin
 for(s=1;s<256;s=s+1) begin
   @(negedge clock);lfsr_seed=s;reset=0;#1;
   samples=samples+1;if(lfsr_out!==lfsr_seed) errors=errors+1;
   @(negedge clock);reset=1;expected=s;seen=0;
   for(j=0;j<255;j=j+1) begin
     @(posedge clock);#1;
     expected=(expected>>1)^(expected[0]?8'hb1:8'h00);
     samples=samples+1;
     if(lfsr_out!==expected || lfsr_out===0 || seen[lfsr_out]===1) errors=errors+1;
     seen[lfsr_out]=1;
   end
   samples=samples+1;if(lfsr_out!==lfsr_seed) errors=errors+1;
 end
 $display("Mismatches: %0d in %0d samples",errors,samples);$finish;
end
initial begin #1000000;$display("TIMEOUT");$finish;end
endmodule

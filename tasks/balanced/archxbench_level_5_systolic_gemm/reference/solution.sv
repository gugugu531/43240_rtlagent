// 本地独立参考：16个有符号乘加PE，依据公开规格。
module solution_pe(input [31:0] north_in,west_in,input clk,rst,
 output reg [31:0] south_out,east_out, output reg [63:0] result);
wire signed [63:0] product=$signed(north_in)*$signed(west_in);
always @(posedge clk) begin
 if(rst) begin south_out<=0;east_out<=0;result<=0;end
 else begin south_out<=north_in;east_out<=west_in;result<=result+product;end
end
endmodule
module TopModule (
    input  [31:0] a_west0, a_west1, a_west2, a_west3,
    input  [31:0] b_north0, b_north1, b_north2, b_north3,
    input         clk, rst,
    output reg    done,
    output [63:0] result0,  result1,  result2,  result3,
    output [63:0] result4,  result5,  result6,  result7,
    output [63:0] result8,  result9,  result10, result11,
    output [63:0] result12, result13, result14, result15
);
wire [31:0] east[0:15],south[0:15];
reg [4:0] count;
always @(posedge clk) begin
 if(rst) begin count<=0;done<=0;end
 else if(count<12) begin count<=count+1; if(count==11) done<=1;end
end
solution_pe p0(.clk(clk),.rst(rst),.west_in(a_west0),.north_in(b_north0),.east_out(east[0]),.south_out(south[0]),.result(result0));
solution_pe p1(.clk(clk),.rst(rst),.west_in(east[0]),.north_in(b_north1),.east_out(east[1]),.south_out(south[1]),.result(result1));
solution_pe p2(.clk(clk),.rst(rst),.west_in(east[1]),.north_in(b_north2),.east_out(east[2]),.south_out(south[2]),.result(result2));
solution_pe p3(.clk(clk),.rst(rst),.west_in(east[2]),.north_in(b_north3),.east_out(east[3]),.south_out(south[3]),.result(result3));
solution_pe p4(.clk(clk),.rst(rst),.west_in(a_west1),.north_in(south[0]),.east_out(east[4]),.south_out(south[4]),.result(result4));
solution_pe p5(.clk(clk),.rst(rst),.west_in(east[4]),.north_in(south[1]),.east_out(east[5]),.south_out(south[5]),.result(result5));
solution_pe p6(.clk(clk),.rst(rst),.west_in(east[5]),.north_in(south[2]),.east_out(east[6]),.south_out(south[6]),.result(result6));
solution_pe p7(.clk(clk),.rst(rst),.west_in(east[6]),.north_in(south[3]),.east_out(east[7]),.south_out(south[7]),.result(result7));
solution_pe p8(.clk(clk),.rst(rst),.west_in(a_west2),.north_in(south[4]),.east_out(east[8]),.south_out(south[8]),.result(result8));
solution_pe p9(.clk(clk),.rst(rst),.west_in(east[8]),.north_in(south[5]),.east_out(east[9]),.south_out(south[9]),.result(result9));
solution_pe p10(.clk(clk),.rst(rst),.west_in(east[9]),.north_in(south[6]),.east_out(east[10]),.south_out(south[10]),.result(result10));
solution_pe p11(.clk(clk),.rst(rst),.west_in(east[10]),.north_in(south[7]),.east_out(east[11]),.south_out(south[11]),.result(result11));
solution_pe p12(.clk(clk),.rst(rst),.west_in(a_west3),.north_in(south[8]),.east_out(east[12]),.south_out(south[12]),.result(result12));
solution_pe p13(.clk(clk),.rst(rst),.west_in(east[12]),.north_in(south[9]),.east_out(east[13]),.south_out(south[13]),.result(result13));
solution_pe p14(.clk(clk),.rst(rst),.west_in(east[13]),.north_in(south[10]),.east_out(east[14]),.south_out(south[14]),.result(result14));
solution_pe p15(.clk(clk),.rst(rst),.west_in(east[14]),.north_in(south[11]),.east_out(east[15]),.south_out(south[15]),.result(result15));
endmodule

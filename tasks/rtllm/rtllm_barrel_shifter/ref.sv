module RefModule (in, ctrl, out);
  input  [7:0] in;
  input [2:0] ctrl;
  output [7:0] out;
  wire [7:0] x,y;
 
//4bit shift right
reference_mux2X1  ins_17 (.in0(in[7]),.in1(1'b0),.sel(ctrl[2]),.out(x[7]));
reference_mux2X1  ins_16 (.in0(in[6]),.in1(1'b0),.sel(ctrl[2]),.out(x[6]));
reference_mux2X1  ins_15 (.in0(in[5]),.in1(1'b0),.sel(ctrl[2]),.out(x[5]));
reference_mux2X1  ins_14 (.in0(in[4]),.in1(1'b0),.sel(ctrl[2]),.out(x[4]));
reference_mux2X1  ins_13 (.in0(in[3]),.in1(in[7]),.sel(ctrl[2]),.out(x[3]));
reference_mux2X1  ins_12 (.in0(in[2]),.in1(in[6]),.sel(ctrl[2]),.out(x[2]));
reference_mux2X1  ins_11 (.in0(in[1]),.in1(in[5]),.sel(ctrl[2]),.out(x[1]));
reference_mux2X1  ins_10 (.in0(in[0]),.in1(in[4]),.sel(ctrl[2]),.out(x[0]));
 
//2 bit shift right
 
reference_mux2X1  ins_27 (.in0(x[7]),.in1(1'b0),.sel(ctrl[1]),.out(y[7]));
reference_mux2X1  ins_26 (.in0(x[6]),.in1(1'b0),.sel(ctrl[1]),.out(y[6]));
reference_mux2X1  ins_25 (.in0(x[5]),.in1(x[7]),.sel(ctrl[1]),.out(y[5]));
reference_mux2X1  ins_24 (.in0(x[4]),.in1(x[6]),.sel(ctrl[1]),.out(y[4]));
reference_mux2X1  ins_23 (.in0(x[3]),.in1(x[5]),.sel(ctrl[1]),.out(y[3]));
reference_mux2X1  ins_22 (.in0(x[2]),.in1(x[4]),.sel(ctrl[1]),.out(y[2]));
reference_mux2X1  ins_21 (.in0(x[1]),.in1(x[3]),.sel(ctrl[1]),.out(y[1]));
reference_mux2X1  ins_20 (.in0(x[0]),.in1(x[2]),.sel(ctrl[1]),.out(y[0]));
 
//1 bit shift right
reference_mux2X1  ins_07 (.in0(y[7]),.in1(1'b0),.sel(ctrl[0]),.out(out[7]));
reference_mux2X1  ins_06 (.in0(y[6]),.in1(y[7]),.sel(ctrl[0]),.out(out[6]));
reference_mux2X1  ins_05 (.in0(y[5]),.in1(y[6]),.sel(ctrl[0]),.out(out[5]));
reference_mux2X1  ins_04 (.in0(y[4]),.in1(y[5]),.sel(ctrl[0]),.out(out[4]));
reference_mux2X1  ins_03 (.in0(y[3]),.in1(y[4]),.sel(ctrl[0]),.out(out[3]));
reference_mux2X1  ins_02 (.in0(y[2]),.in1(y[3]),.sel(ctrl[0]),.out(out[2]));
reference_mux2X1  ins_01 (.in0(y[1]),.in1(y[2]),.sel(ctrl[0]),.out(out[1]));
reference_mux2X1  ins_00 (.in0(y[0]),.in1(y[1]),.sel(ctrl[0]),.out(out[0]));

endmodule

module reference_mux2X1( in0,in1,sel,out);
input in0,in1;
input sel;
output out;
assign out=(sel)?in1:in0;
endmodule
